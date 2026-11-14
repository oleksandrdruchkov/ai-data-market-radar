"""
collectors/arxiv_counts.py
Скільки статей ШІ щомісяця виходить на ArXiv за кожним напрямом -> fct_metric_values.
Без моделі: arXiv API повертає загальну кількість знайдених статей (opensearch:totalResults),
самі статті не завантажуються.

  arxiv_papers_total     усі статті місяця в категоріях ШІ (CATEGORIES), шт.
  arxiv_share_<напрям>   % статей місяця, що відповідають запиту напряму;
                         numerator = статей напряму, denominator = усіх статей

Напрями (DIRECTIONS) - пошук за фразами в анотаціях. Одна стаття може потрапити в кілька
напрямів, тож частки не складаються в 100 %. Змінили запит напряму -> підніміть METHOD_VERSION,
бо ряд змінює зміст.

Перший запуск - уся історія з ARXIV_COUNTS_START (за замовчуванням 2023-01), далі -
перерахунок двох останніх місяців (arXiv дописує статті із запізненням). Поточний місяць
неповний: is_estimate = true.

arXiv просить не частіше одного запиту на 3 секунди: перший запуск ~ (місяців × 6) × 3 с,
для 2023-01..2026-11 це близько 15 хвилин.

Змінні: ARXIV_COUNTS_START="2023-01-01"
Запуск: python -m collectors.arxiv_counts
"""

from __future__ import annotations

import os
import time
import calendar
import xml.etree.ElementTree as ET
from datetime import date

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult

API_URL = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}totalResults"
PAUSE_SECONDS = 3.0
METHOD_VERSION = "v1"
TOTAL_ID = "arxiv_papers_total"

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.RO", "cs.MA"]

# id -> (назва UA, назва EN, фрази для пошуку в анотації)
DIRECTIONS: dict[str, tuple[str, str, list[str]]] = {
    "agents": ("Агенти, що діють самі", "Autonomous agents",
               ["LLM agent", "LLM agents", "autonomous agent", "autonomous agents", "agentic", "tool use"]),
    "ai_science": ("ШІ веде дослідження сам", "AI doing research itself",
                   ["AI scientist", "automated scientific discovery", "autonomous research",
                    "automated research", "self-improving", "recursive self-improvement"]),
    "robots": ("Роботи і фізичний світ", "Robots and the physical world",
               ["robot", "robotic", "embodied", "vision-language-action", "humanoid"]),
    "reasoning": ("Міркування", "Reasoning",
                  ["test-time compute", "chain of thought", "chain-of-thought", "reasoning model",
                   "reasoning models"]),
    "safety": ("Безпека і контроль", "Safety and control",
               ["AI safety", "AI alignment", "interpretability", "red teaming", "jailbreak",
                "oversight"]),
}


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
        parts.append("(" + " OR ".join(f'abs:"{p}"' for p in phrases) + ")")
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

    def since(self, metric_id: str, region: str) -> date:
        """Перший запуск - з ARXIV_COUNTS_START; далі - два останні місяці."""
        rows = self.db.select("fct_metric_values", "period_start",
                              eq={"metric_id": metric_id, "region": region}, limit=1)
        if not rows:
            return date.fromisoformat(os.getenv("ARXIV_COUNTS_START", "2023-01-01")).replace(day=1)
        y, m = self.today.year, self.today.month - 1
        if m == 0:
            y, m = y - 1, 12
        return date(y, m, 1)

    def count(self, query: str) -> int:
        if self._calls:
            self.sleep(PAUSE_SECONDS)
        self._calls += 1
        resp = get_with_retry(API_URL, params={"search_query": query, "start": 0, "max_results": 0},
                              headers=HEADERS, timeout=60)
        return parse_total(resp.text)

    def fetch_series(self) -> list[SeriesResult]:
        start = min(self.since(TOTAL_ID, "GLOBAL"),
                    *(self.since(share_id(k), "GLOBAL") for k in DIRECTIONS))
        months = months_between(start, self.today)

        total = SeriesResult(metric_id=TOTAL_ID, region="GLOBAL")
        shares = {k: SeriesResult(metric_id=share_id(k), region="GLOBAL") for k in DIRECTIONS}

        for m in months:
            _, last = month_bounds(m)
            partial = last >= self.today
            try:
                n_all = self.count(build_query(m, None))
            except Exception as e:
                total.error = f"{m:%Y-%m}: {type(e).__name__}: {e}"
                break                                   # без знаменника частки не рахуються
            if n_all == 0:
                total.error = f"{m:%Y-%m}: arXiv повернув 0 статей - підозріло, зупинка"
                break
            total.points.append((m, float(n_all)))
            total.extra[m] = {"period_end": last.isoformat(), "is_estimate": partial}
            for k, (_, _, phrases) in DIRECTIONS.items():
                s = shares[k]
                if s.error:
                    continue
                try:
                    n = self.count(build_query(m, phrases))
                except Exception as e:
                    s.error = f"{m:%Y-%m}: {type(e).__name__}: {e}"
                    continue
                s.points.append((m, round(100.0 * n / n_all, 3)))
                s.extra[m] = {"period_end": last.isoformat(), "is_estimate": partial,
                              "numerator": float(n), "denominator": float(n_all)}

        # Ряд з помилкою не пишеться зовсім (правило каркаса), тож частково зібрані
        # місяці не змішуються з дірками. Без знаменника не пишуться й частки.
        if total.error:
            for s in shares.values():
                s.error = s.error or f"немає знаменника: {total.error}"
        return [total, *shares.values()]


if __name__ == "__main__":
    ArxivCounts().run()
