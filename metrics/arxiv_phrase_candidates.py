"""
metrics/arxiv_phrase_candidates.py
Раз на місяць: нові терміни з досліджень, яких ще немає у фразах напрямів ArXiv.

Звідки: fct_arxiv_signals - щоденні сигнали, де Gemini вже назвав навичку кожної статті
(predicted_skill). Навичка, у тексті якої немає жодної фрази напрямів (collectors/arxiv_counts.py
плюс уже схвалені людиною), стає кандидатом.

Для кожного кандидата:
  n_signals            скільки сигналів місяця мали цю навичку;
  n_arxiv_month        скільки статей ШІ того ж місяця знаходить ця фраза в arXiv (масштаб);
  suggested_direction  напрям, чиї фрази найчастіше трапляються в назвах і висновках цих статей;
  example_titles       до трьох назв статей.

Пише в ops_phrase_candidates. Рішення людини (status = added / rejected) не перезаписуються:
відхилена навичка більше не з'являється, схвалена додається до фраз, і збирач arxiv_counts
перераховує історію новим списком.

Змінні: PHRASE_CANDIDATES_MONTH="2026-10"  (за замовчуванням - минулий місяць)
        PHRASE_CANDIDATES_MAX=25           (скільки кандидатів перевіряти в arXiv)
Запуск: python -m metrics.arxiv_phrase_candidates
"""

from __future__ import annotations

import os
import re
import logging
from collections import Counter, defaultdict
from datetime import date

from core.db import Db, iso, utcnow
from collectors import arxiv_counts as ac

log = logging.getLogger("radar.phrase_candidates")
SOURCE = "arxiv_phrase_candidates"


def norm(text: str | None) -> str:
    """Нижній регістр, дефіси й зайві пробіли зведені до одного пробілу."""
    return re.sub(r"[\s\-_/]+", " ", (text or "").lower()).strip()


def covered(skill: str, phrases: list[str]) -> bool:
    """Навичку вже ловить хоч одна фраза (фраза міститься в тексті навички)."""
    s = norm(skill)
    return any(norm(p) and norm(p) in s for p in phrases)


def guess_direction(texts: list[str], directions: dict) -> str | None:
    """Напрям, чиї фрази найчастіше трапляються в назвах і висновках статей кандидата."""
    hits: Counter = Counter()
    for t in texts:
        nt = norm(t)
        for k, (_, _, phrases) in directions.items():
            if any(norm(p) in nt for p in phrases):
                hits[k] += 1
    return hits.most_common(1)[0][0] if hits else None


def find_candidates(signals: list[dict], directions: dict) -> list[dict]:
    """Чиста функція: сигнали місяця -> кандидати, найчастіші першими."""
    all_phrases = [p for _, _, ph in directions.values() for p in ph]
    groups: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, Counter] = defaultdict(Counter)
    for s in signals:
        skill = (s.get("predicted_skill") or "").strip()
        if not skill or covered(skill, all_phrases):
            continue
        groups[norm(skill)].append(s)
        names[norm(skill)][skill] += 1
    out = []
    for key, rows in groups.items():
        texts = [f"{r.get('title') or ''} {r.get('signal_summary') or ''}" for r in rows]
        out.append({
            "skill_norm": key,
            "phrase": names[key].most_common(1)[0][0],
            "n_signals": len(rows),
            "suggested_direction": guess_direction(texts, directions),
            "example_titles": [r.get("title") for r in rows[:3] if r.get("title")],
        })
    out.sort(key=lambda c: (-c["n_signals"], c["skill_norm"]))
    return out


def previous_month(today: date) -> date:
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def run(db: Db | None = None, today: date | None = None) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db = db or Db()
    today = today or date.today()
    raw = os.getenv("PHRASE_CANDIDATES_MONTH")
    month = date.fromisoformat(raw + "-01") if raw else previous_month(today)
    first, last = ac.month_bounds(month)
    run_id = db.start_run(SOURCE, "1")
    stats = {"seen": 0, "new": 0, "updated": 0, "failed": 0}
    error = None
    try:
        counter = ac.ArxivCounts(db=db)          # фрази з коду + схвалені людиною
        directions = counter.directions
        rows = db.select("fct_arxiv_signals",
                         "predicted_skill,title,signal_summary,event_date,published_date,extraction_method",
                         order="id", desc=True, limit=1000)       # найсвіжіші; ~150 сигналів на місяць
        signals = [r for r in rows
                   if r.get("extraction_method") != "legacy_fallback"
                   and first.isoformat() <= str(r.get("event_date") or r.get("published_date") or "")[:10] <= last.isoformat()]
        stats["seen"] = len(signals)
        cands = find_candidates(signals, directions)

        known = {r["skill_norm"]: r for r in db.select("ops_phrase_candidates", "skill_norm,status,first_month")}
        fresh = [c for c in cands if known.get(c["skill_norm"], {}).get("status", "new") == "new"]
        limit = int(os.getenv("PHRASE_CANDIDATES_MAX", "25"))
        out = []
        for c in fresh[:limit]:
            try:
                c["n_arxiv_month"] = counter.count(ac.build_query(month, [c["phrase"]]))
            except Exception as e:
                c["n_arxiv_month"] = None
                stats["failed"] += 1
                log.warning(f"{c['phrase']}: arXiv: {e}")
            prev = known.get(c["skill_norm"])
            c["first_month"] = (prev or {}).get("first_month") or first.isoformat()
            c["last_month"] = first.isoformat()
            c["updated_at"] = iso(utcnow())
            out.append(c)
            stats["updated" if prev else "new"] += 1
        if out:
            db.upsert("ops_phrase_candidates", out, on_conflict="skill_norm")   # status не передається - рішення людини лишається
        log.info(f"{month:%Y-%m}: сигналів {len(signals)}, кандидатів {len(cands)}, записано {len(out)}")
    except Exception as e:
        log.exception("Пошук кандидатів впав")
        error = f"{type(e).__name__}: {e}"
    db.finish_run(run_id, "failed" if error else ("partial" if stats["failed"] else "ok"), stats, error)
    return stats


if __name__ == "__main__":
    run()
