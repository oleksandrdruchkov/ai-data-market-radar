"""
collectors/jobs_adzuna.py
Вакансії з Adzuna API (США, Велика Британія, Сінгапур, Індія; ринки та запити налаштовуються).
APAC представлений Сінгапуром та Індією: Китаю, Японії й Кореї в Adzuna немає.
Замінює main_pipeline.py.

Важливо: Adzuna повертає лише першу сторінку пошуку, а не повний список ринку,
тому tracks_presence = False - вакансію, що випала з топу видачі, не можна
вважати закритою.

Розбір навичок, напряму, рівня й формату роботи - ключовими словами, без мовної моделі
(collectors/_job_keywords.py), так само як вакансії китайських лабораторій. До версії 3 розбір
робила Gemini (prompt vacancy_v2); цей спосіб лишено запасним: ADZUNA_PARSE=llm.

Вакансії, зібрані раніше й розібрані іншим способом (моделлю або до переходу на каркас), після
кожного запуску перерозбираються ключовими словами з уже збереженого тексту (reparse_existing):
усі регіони рахуються одним способом. Те саме спрацює після зміни словника (KEYWORDS_VERSION).

Змінні: ADZUNA_APP_ID, ADZUNA_APP_KEY (обов'язкові)
        ADZUNA_MARKETS="us:US:USD,gb:Europe:GBP,sg:APAC:SGD,in:APAC:INR"   ADZUNA_QUERY="data engineer python"
        ADZUNA_PER_PAGE=20
        ADZUNA_PARSE="keywords" (за замовчуванням) | "llm"
Запуск: python -m collectors.jobs_adzuna            (запис у базу)
        python -m collectors.jobs_adzuna --dry-run  (лише друк розібраного, без бази)
"""

from __future__ import annotations

import os
import sys

from core import RawItem
from core.http import get_with_retry
from collectors import _job_keywords as keywords
from collectors._jobs_common import JobsCollector

PROMPT_VERSION = "vacancy_v2"
DEFAULT_MARKETS = "us:US:USD,gb:Europe:GBP,sg:APAC:SGD,in:APAC:INR"


def _markets() -> list[dict]:
    out = []
    for chunk in os.getenv("ADZUNA_MARKETS", DEFAULT_MARKETS).split(","):
        code, region, currency = (p.strip() for p in chunk.split(":"))
        out.append({"country_code": code, "region": region, "currency": currency})
    return out


class AdzunaJobs(JobsCollector):
    source = "adzuna"
    collection_method = "api"
    tracks_presence = False
    collector_version = "3"       # 3: розбір ключовими словами замість Gemini

    def fetch(self):
        app_id = os.getenv("ADZUNA_APP_ID", "").strip()
        app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            raise RuntimeError("Не задано ADZUNA_APP_ID / ADZUNA_APP_KEY")
        query = os.getenv("ADZUNA_QUERY", "data engineer python")
        per_page = int(os.getenv("ADZUNA_PER_PAGE", "20"))

        for m in _markets():
            resp = get_with_retry(        # 503/429 від Adzuna - повтор через 5 і 15 с
                f"https://api.adzuna.com/v1/api/jobs/{m['country_code']}/search/1",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": per_page,
                        "what": query, "content-type": "application/json"},
                timeout=20,
            )
            # після всіх спроб помилка ринку = помилка fetch, а не тихі 0 записів
            results = resp.json().get("results", [])
            self.log.info(f"Adzuna {m['country_code'].upper()}: {len(results)} вакансій")
            for item in results:
                title = item.get("title", "")
                company = (item.get("company") or {}).get("display_name", "")
                desc = item.get("description", "")
                yield RawItem(
                    # id Adzuna унікальний лише в межах країни
                    external_id=f"{m['country_code']}:{item.get('id')}",
                    payload={**item, "_market": m, "_query": query},
                    content_key=f"{title}|{company}|{desc}",
                )

    def parse(self, raw: RawItem) -> dict | None:
        item, m = raw.payload, raw.payload["_market"]
        if os.getenv("ADZUNA_PARSE", "keywords") == "llm":
            res = self.extract(raw, item.get("title", ""), item.get("description", ""),
                               translate=False, prompt_version=PROMPT_VERSION)
            if res is None:
                return None
            x = res.data
            parsed = {"experience_level": x.experience_level, "work_model": x.work_model, "track": x.track,
                      "extraction_method": res.method, "prompt_version": PROMPT_VERSION, "_skills": x.skills}
        else:
            parsed = keywords.extract(item.get("title", ""), item.get("description", ""),
                                      (item.get("category") or {}).get("label"))
        created = item.get("created")
        return {
            "title": item.get("title") or "",
            "company": (item.get("company") or {}).get("display_name"),
            "location": (item.get("location") or {}).get("display_name"),
            "region": m["region"],
            "country_code": m["country_code"].upper(),
            "currency": m["currency"],
            "salary_period": "yearly",
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "salary_is_predicted": str(item.get("salary_is_predicted", "0")) == "1",
            "source_url": item.get("redirect_url"),
            "event_date": created[:10] if created else None,
            "posted_at": created,
            **parsed,
        }

    def reparse_existing(self) -> dict:
        """Активні вакансії Adzuna, розібрані не поточним словником, перерозбираються ключовими словами
        з тексту, збереженого в raw_items. Змінюються лише поля розбору й навички; дати, зарплата,
        регіон і last_seen_at не чіпаються. Повертає {"checked", "updated", "no_text"}."""
        rows = self.db.select(self.fact_table, "id,raw_item_id,title,extraction_method",
                              eq={"source": self.source, "is_active": True})
        todo = [r for r in rows if r.get("extraction_method") != keywords.METHOD]
        stats = {"checked": len(rows), "updated": 0, "no_text": 0}
        raw_ids = sorted({r["raw_item_id"] for r in todo if r.get("raw_item_id")})
        payloads: dict[int, dict] = {}
        for i in range(0, len(raw_ids), 100):
            for raw in self.db.select("raw_items", "raw_id,payload", in_={"raw_id": raw_ids[i:i + 100]}):
                payloads[raw["raw_id"]] = raw.get("payload") or {}
        for r in todo:
            item = payloads.get(r.get("raw_item_id"))
            if not item or not (item.get("title") or r.get("title")):
                stats["no_text"] += 1
                continue
            parsed = keywords.extract(item.get("title") or r["title"], item.get("description", ""),
                                      (item.get("category") or {}).get("label") if isinstance(item.get("category"), dict) else None)
            skills = parsed.pop("_skills")
            self.db.update(self.fact_table, parsed, eq={"id": r["id"]})
            self.write_skills(r["id"], skills)
            stats["updated"] += 1
        self.log.info(f"Перерозбір ключовими словами ({keywords.KEYWORDS_VERSION}): перевірено {stats['checked']}, "
                      f"оновлено {stats['updated']}, без збереженого тексту {stats['no_text']}")
        return stats


def dry_run() -> int:
    """Жива видача Adzuna -> розбір ключовими словами -> друк зведення. Без бази й без моделі."""
    import logging
    from collections import Counter
    logging.basicConfig(level=logging.INFO)
    c = AdzunaJobs.__new__(AdzunaJobs)
    c.log = logging.getLogger("dry-run.adzuna")
    facts = [c.parse(raw) for raw in c.fetch()]
    print(f"\n=== Adzuna: {len(facts)} вакансій, з навичками {sum(1 for f in facts if f['_skills'])}")
    print("  регіони:", dict(Counter(f["region"] for f in facts)))
    print("  напрями:", dict(Counter(f["track"] for f in facts).most_common()))
    print("  рівні:", dict(Counter(f["experience_level"] for f in facts).most_common()))
    print("  формат:", dict(Counter(f["work_model"] for f in facts).most_common()))
    print("  навички:", ", ".join(f"{n} {k}" for n, k in Counter(s.name for f in facts for s in f["_skills"]).most_common(40)))
    print("  без навичок:", " | ".join(f["title"][:50] for f in facts if not f["_skills"])[:900])
    print("  напрям Other:", " | ".join(f["title"][:50] for f in facts if f["track"] == "Other")[:900])
    for f in facts[:60:3]:
        print(f"  - {f['region']} | {f['title'][:60]} | {f['track']} / {f['experience_level']} / {f['work_model']} | "
              f"{[s.name for s in f['_skills']]}")
    return 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        sys.exit(dry_run())
    collector = AdzunaJobs()
    try:
        collector.run()
    finally:
        # і після невдалого збору: перерозбір працює з уже збереженим текстом
        if os.getenv("ADZUNA_PARSE", "keywords") != "llm":
            collector.reparse_existing()
