"""
collectors/arxiv_counts.py
Скільки статей ШІ щомісяця виходить на ArXiv за кожним напрямом -> fct_metric_values.
Без моделі: arXiv API повертає загальну кількість знайдених статей (opensearch:totalResults),
самі статті не завантажуються.

  arxiv_papers_total     усі статті місяця в категоріях ШІ (CATEGORIES), шт.
  arxiv_share_<напрям>   % статей місяця, що відповідають запиту напряму;
                         numerator = статей напряму, denominator = усіх статей

Напрями (DIRECTIONS) - пошук за фразами в назві та анотації. Одна стаття може потрапити в кілька
напрямів, тож частки не складаються в 100 %.

До фраз з коду додаються фрази, які людина схвалила на сторінці перевірки
(ops_phrase_candidates, status = 'added'; кандидатів готує metrics/arxiv_phrase_candidates.py).
Версія методу = METHOD_VERSION + відбиток повного списку фраз. Список змінився -> версія
змінилась -> збирач перераховує всю історію новим списком, щоб ряд не мав «шва».

Перший запуск - уся історія з ARXIV_COUNTS_START (за замовчуванням 2023-01), далі -
перерахунок двох останніх місяців (arXiv дописує статті із запізненням). Поточний місяць
неповний: is_estimate = true.

arXiv обмежує частоту (429), тому пауза 6 с і не більше ARXIV_COUNTS_MAX_QUERIES запитів
за запуск (120 = 20 місяців). Місяць пишеться лише цілим (усі статті + усі напрями), а
наступний запуск продовжує з останнього записаного місяця, тож історія з 2023 року
збирається за 2-3 щоденні запуски.

Змінні: ARXIV_COUNTS_START="2023-01-01"   ARXIV_COUNTS_MAX_QUERIES=120
        PHRASE_CHECK_DIRECTION=agents  (для --check: лише один напрям, щоб не впертися в ліміт)
Запуск: python -m collectors.arxiv_counts
Перевірка фраз (лише друк, без запису): python -m collectors.arxiv_counts --check
"""

from __future__ import annotations

import os
import time
import hashlib
import calendar
import xml.etree.ElementTree as ET
from datetime import date

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult

API_URL = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}totalResults"
PAUSE_SECONDS = 6.0             # arXiv просить >= 3 с; на 3 с після ~80 запитів відповідав 429
RETRY_PAUSES = (60, 180, 300)   # 429/5xx: arXiv відпускає обмеження лише через кілька хвилин
MAX_QUERIES = 120               # запитів за один запуск; решта історії - наступного дня
METHOD_VERSION = "v1"
TOTAL_ID = "arxiv_papers_total"

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.RO", "cs.MA"]

# id -> (назва UA, назва EN, фрази для пошуку в анотації)
# Фрази - лише такі, що в категоріях ШІ майже завжди означають саме цей напрям.
# Багатозначні слова беруться у сполученні: не «oversight», а «scalable oversight».
# Перевірити, скільки статей дає кожна фраза: python -m collectors.arxiv_counts --check
DIRECTIONS: dict[str, tuple[str, str, list[str]]] = {
    "agents": ("Агенти, що діють самі", "Autonomous agents", [
        "LLM agent", "LLM agents", "LLM-based agent", "LLM-based agents",
        "language agent", "language agents", "AI agent", "AI agents",
        "autonomous agent", "autonomous agents", "agentic",
        "tool use", "tool-use", "tool calling", "function calling",
        "computer use", "computer-use agent", "GUI agent", "GUI agents",
        "web agent", "web agents", "coding agent", "coding agents",
        "software engineering agent", "agent memory", "long-horizon agent",
        "multi-agent LLM", "LLM-based multi-agent", "agent swarm",
    ]),
    "ai_science": ("ШІ веде дослідження сам", "AI doing research itself", [
        "AI scientist", "AI scientists", "AI co-scientist",
        "automated scientific discovery", "autonomous scientific discovery",
        "autonomous research", "automated research", "research agent", "research agents",
        "automated AI research", "AI research automation", "automating AI research",
        "automated machine learning research", "automated alignment research",
        "self-improving", "recursive self-improvement", "self-improving agent",
        "automated hypothesis generation", "LLM-driven discovery",
        "self-driving laboratory", "self-driving lab", "autonomous laboratory",
    ]),
    "robots": ("Роботи і фізичний світ", "Robots and the physical world", [
        "robot", "robots", "robotic", "robotics", "humanoid",
        "embodied", "embodied agent", "embodied AI",
        "vision-language-action", "VLA model", "VLA models",
        "dexterous manipulation", "robot manipulation", "robotic manipulation",
        "sim-to-real", "robot learning", "legged locomotion",
    ]),
    "reasoning": ("Міркування", "Reasoning", [
        "test-time compute", "test-time scaling", "inference-time compute", "inference-time scaling",
        "chain of thought", "chain-of-thought", "long chain-of-thought",
        "reasoning model", "reasoning models", "large reasoning model", "large reasoning models",
        "reinforcement learning with verifiable rewards", "verifiable rewards",
        "process reward model", "latent reasoning", "thinking tokens",
    ]),
    "safety": ("Безпека і контроль", "Safety and control", [
        "AI safety", "AI alignment", "value alignment", "alignment of language models",
        "interpretability", "mechanistic interpretability", "sparse autoencoder", "sparse autoencoders",
        "red teaming", "red-teaming", "jailbreak", "jailbreaks", "jailbreaking",
        "scalable oversight", "human oversight", "AI control", "chain-of-thought monitoring",
        "deceptive alignment", "emergent misalignment", "scheming", "sandbagging",
        "reward hacking", "evaluation awareness", "dangerous capabilities", "dangerous capability",
        "model organisms", "corrigibility",
    ]),
}


def merge_phrases(base: dict[str, tuple[str, str, list[str]]],
                  extra: list[dict]) -> dict[str, tuple[str, str, list[str]]]:
    """Фрази з коду + схвалені людиною (рядки ops_phrase_candidates: phrase, direction).
    Дублікати (без різниці регістру) і невідомі напрями відкидаються."""
    out = {k: (ua, en, list(ph)) for k, (ua, en, ph) in base.items()}
    for r in extra:
        k, phrase = r.get("direction"), (r.get("phrase") or "").strip()
        if k not in out or not phrase:
            continue
        if phrase.lower() not in {p.lower() for p in out[k][2]}:
            out[k][2].append(phrase)
    return out


def fingerprint(directions: dict[str, tuple[str, str, list[str]]]) -> str:
    """Короткий відбиток списку фраз: інший список - інший відбиток."""
    flat = "|".join(f"{k}:" + ",".join(sorted(p.lower() for p in ph))
                    for k, (_, _, ph) in sorted(directions.items()))
    return hashlib.sha1(flat.encode("utf-8")).hexdigest()[:8]


def share_id(direction: str) -> str:
    return f"arxiv_share_{direction}"


def month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])


def months_between(start: date, end: date) -> list[date]:
    """Перші дні місяців від start до end включно."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_query(month: date, phrases: list[str] | None) -> str:
    """Запит arXiv: категорії ШІ, (фрази напряму в анотації), дата подання в межах місяця."""
    first, last = month_bounds(month)
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    when = f"submittedDate:[{first:%Y%m%d}0000 TO {last:%Y%m%d}2359]"
    parts = [f"({cats})"]
    if phrases:
        parts.append("(" + " OR ".join(f'ti:"{p}" OR abs:"{p}"' for p in phrases) + ")")
    parts.append(when)
    return " AND ".join(parts)


def parse_total(xml_text: str) -> int:
    """Чиста функція: opensearch:totalResults з відповіді arXiv. Немає - помилка, а не нуль."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"arXiv: відповідь не XML: {xml_text[:120]!r}") from e
    node = root.find(OPENSEARCH)
    if node is None or not (node.text or "").strip().isdigit():
        raise ValueError(f"arXiv: немає totalResults: {xml_text[:200]!r}")
    return int(node.text.strip())


class ArxivCounts(MetricSeriesCollector):
    source = "arxiv_counts"
    collector_version = "1"
    method_version = METHOD_VERSION

    def __init__(self, *a, sleep=time.sleep, today: date | None = None, **k):
        super().__init__(*a, **k)
        self.sleep = sleep
        self.today = today or date.today()
        self._calls = 0
        self.directions = merge_phrases(DIRECTIONS, self.approved_phrases())
        self.method_version = f"{METHOD_VERSION}-{fingerprint(self.directions)}"

    def approved_phrases(self) -> list[dict]:
        try:
            return self.db.select("ops_phrase_candidates", "phrase,direction", eq={"status": "added"})
        except Exception as e:                      # таблиці ще немає - працюємо зі списком з коду
            self.log.warning(f"ops_phrase_candidates недоступна: {e}")
            return []

    def since(self, metric_id: str, region: str) -> date:
        """Перший запуск або змінений список фраз - уся історія з ARXIV_COUNTS_START;
        інакше - два останні місяці або місяць, на якому перервався минулий збір."""
        rows = self.db.select("fct_metric_values", "period_start,method_version",
                              eq={"metric_id": metric_id, "region": region},
                              order="period_start", desc=True, limit=1)
        if not rows or rows[0].get("method_version") != self.method_version:
            return date.fromisoformat(os.getenv("ARXIV_COUNTS_START", "2023-01-01")).replace(day=1)
        y, m = self.today.year, self.today.month - 1
        if m == 0:
            y, m = y - 1, 12
        last_saved = date.fromisoformat(str(rows[0]["period_start"])[:10])
        return min(last_saved, date(y, m, 1))       # збір історії перервався - продовжити звідти

    def count(self, query: str) -> int:
        if self._calls:
            self.sleep(PAUSE_SECONDS)
        self._calls += 1
        # max_results=1, а не 0: деякі сервери arXiv на 0 відповідають помилкою
        resp = get_with_retry(API_URL, params={"search_query": query, "start": 0, "max_results": 1},
                              headers=HEADERS, timeout=60, pauses=RETRY_PAUSES, sleep=self.sleep)
        return parse_total(resp.text)

    def fetch_series(self) -> list[SeriesResult]:
        start = min(self.since(TOTAL_ID, "GLOBAL"),
                    *(self.since(share_id(k), "GLOBAL") for k in self.directions))
        months = months_between(start, self.today)
        budget = int(os.getenv("ARXIV_COUNTS_MAX_QUERIES", str(MAX_QUERIES)))
        per_month = 1 + len(self.directions)

        total = SeriesResult(metric_id=TOTAL_ID, region="GLOBAL")
        shares = {k: SeriesResult(metric_id=share_id(k), region="GLOBAL") for k in self.directions}
        self.stop_reason = None
        used = 0

        # Місяць записується лише цілим: усі статті + усі напрями. Збій або вичерпаний
        # ліміт запитів - зупинка; зібрані місяці пишуться, решту дозбирає наступний запуск.
        for m in months:
            if used + per_month > budget:
                self.stop_reason = f"ліміт {budget} запитів за запуск; продовження з {m:%Y-%m} наступного разу"
                break
            _, last = month_bounds(m)
            partial = last >= self.today
            used += per_month
            try:
                n_all = self.count(build_query(m, None))
                if n_all == 0:
                    raise ValueError("arXiv повернув 0 статей - підозріло")
                ns = {k: self.count(build_query(m, ph)) for k, (_, _, ph) in self.directions.items()}
            except Exception as e:
                self.stop_reason = f"{m:%Y-%m}: {type(e).__name__}: {e}"
                break
            total.points.append((m, float(n_all)))
            total.extra[m] = {"period_end": last.isoformat(), "is_estimate": partial}
            for k, n in ns.items():
                shares[k].points.append((m, round(100.0 * n / n_all, 3)))
                shares[k].extra[m] = {"period_end": last.isoformat(), "is_estimate": partial,
                                      "numerator": float(n), "denominator": float(n_all)}

        if self.stop_reason:
            self.log.warning(f"Зупинка: {self.stop_reason}")
            if not total.points:                        # не зібрано жодного місяця - це помилка запуску
                for r in (total, *shares.values()):
                    r.error = self.stop_reason
        return [total, *shares.values()]


def phrase_report(month: date, count=None, sleep=time.sleep, only: str | None = None,
                  out=print) -> list[tuple[str, str, int]]:
    """Скільки статей місяця дає кожна фраза окремо - щоб знайти зашумлені фрази.
    Друкує рядок одразу після кожного запиту; при збої arXiv зупиняється з частковим результатом."""
    c = ArxivCounts.__new__(ArxivCounts)
    c.sleep, c._calls = sleep, 0
    count = count or c.count
    rows: list[tuple[str, str, int]] = []
    try:
        total = count(build_query(month, None))
        rows.append(("всього", "", total))
        out(f"Місяць {month:%Y-%m}, усіх статей ШІ: {total}")
        for k, (_, _, phrases) in DIRECTIONS.items():
            if only and k != only:
                continue
            for label, ph in [("УСІ ФРАЗИ", phrases), *((p, [p]) for p in phrases)]:
                n = count(build_query(month, ph))
                rows.append((k, label, n))
                out(f"{k:12} {n:6} {100 * n / total:6.2f} %  {label}")
    except Exception as e:
        out(f"ЗУПИНЕНО після {len(rows)} рядків: {type(e).__name__}: {str(e)[:200]}")
    return rows


def probe(sleep=time.sleep) -> None:
    """Діагностика: які частини запиту arXiv приймає. Друкує статус кожного варіанта."""
    import requests
    m = date.today().replace(day=1)
    first, last = month_bounds(date(m.year - (m.month == 1), 12 if m.month == 1 else m.month - 1, 1))
    when = f"submittedDate:[{first:%Y%m%d}0000 TO {last:%Y%m%d}2359]"
    variants = [
        ("як у збирачі сигналів", "cat:cs.AI OR cat:cs.CL OR cat:cs.LG", 5),
        ("max_results=0", "cat:cs.AI", 0),
        ("max_results=1", "cat:cs.AI", 1),
        ("дужки", "(cat:cs.AI OR cat:cs.LG)", 1),
        ("дата", f"cat:cs.AI AND {when}", 1),
        ("дужки + дата", f"(cat:cs.AI OR cat:cs.LG) AND {when}", 1),
        ("фраза в анотації", 'cat:cs.AI AND abs:"AI agent"', 1),
        ("повний запит", build_query(first, None), 1),
    ]
    for name, q, mx in variants:
        try:
            r = requests.get(API_URL, params={"search_query": q, "start": 0, "max_results": mx},
                             headers=HEADERS, timeout=60)
            extra = parse_total(r.text) if r.ok else r.text[:150].replace("\n", " ")
            print(f"{r.status_code}  {name:24} {extra}")
        except Exception as e:
            print(f"ERR  {name:24} {type(e).__name__}: {e}")
        sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        probe()
    elif "--check" in sys.argv:
        t = date.today()
        prev = date(t.year - (t.month == 1), 12 if t.month == 1 else t.month - 1, 1)
        phrase_report(prev, only=os.getenv("PHRASE_CHECK_DIRECTION") or None)
    else:
        ArxivCounts().run()
