"""
collectors/indeed_ai_tracker.py
Частка вакансій зі згадкою ШІ серед усіх вакансій на Indeed -> fct_metric_values.

  indeed_ai_share   % вакансій, у назві чи описі яких є терміни ШІ
                    (machine learning, data science, artificial intelligence тощо)

Джерело - Indeed Hiring Lab AI Tracker, репозиторій github.com/hiring-lab/ai-tracker,
файл AI_posting.csv: колонки date, jobcountry, *_share. Ряд щоденний (ковзне
7-денне середнє), репозиторій оновлюється раз на місяць. Ліцензія CC BY 4.0:
на табло підписувати «Indeed Hiring Lab AI Tracker».

Перший запуск бере всю історію файлу (з початку наявності даних), наступні -
останні LOOKBACK_DAYS днів, щоб підхопити уточнення джерела.

Обмеження ряду: рахує ключові слова в оголошенні, а не посади ШІ-фахівців. Зміни
правил оформлення вакансій можуть його зсувати (напр., Онтаріо з 2026 р. вимагає
розкривати використання ШІ при наймі) - тому за замовчуванням лише US, GB, DE.

Змінні: INDEED_AI_REGIONS="US,GB,DE"
        INDEED_AI_URL - інша адреса файлу (за замовчуванням raw.githubusercontent.com)
Запуск: python -m collectors.indeed_ai_tracker
"""

from __future__ import annotations

import io
import csv
import os
from datetime import date

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult, LOOKBACK_DAYS  # noqa: F401

DEFAULT_URL = "https://raw.githubusercontent.com/hiring-lab/ai-tracker/main/AI_posting.csv"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
METRIC_ID = "indeed_ai_share"


def parse_ai_tracker_csv(text: str) -> dict[str, list[tuple[date, float]]]:
    """Чиста функція: {країна: [(дата, частка %)...]} за зростанням дати.

    Колонки шукаються за назвою: date, jobcountry і перша, що закінчується на _share.
    Порожні значення пропускаються. Незнайомий формат або жодного рядка - помилка."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip() for h in (next(reader, None) or [])]
    low = [h.lower() for h in header]
    try:
        i_date = low.index("date")
        i_cc = low.index("jobcountry")
    except ValueError:
        raise ValueError(f"AI Tracker: немає колонок date/jobcountry: {header[:6]}") from None
    shares = [i for i, h in enumerate(low) if h.endswith("_share")]
    if not shares:
        raise ValueError(f"AI Tracker: немає колонки *_share: {header[:6]}")
    i_val = shares[0]

    out: dict[str, list[tuple[date, float]]] = {}
    for row in reader:
        if len(row) <= max(i_date, i_cc, i_val):
            continue
        raw = row[i_val].strip()
        if raw in ("", ".", "NA", "nan"):
            continue
        v = float(raw)
        if not 0 <= v <= 100:
            raise ValueError(f"AI Tracker: частка поза 0-100: {row}")
        cc = row[i_cc].strip().upper()
        out.setdefault(cc, []).append((date.fromisoformat(row[i_date].strip()[:10]), v))
    if not out:
        raise ValueError("AI Tracker: у файлі немає жодного значення")
    for pts in out.values():
        pts.sort()
    return out


class IndeedAiTracker(MetricSeriesCollector):
    source = "indeed_ai_tracker"
    collector_version = "1"
    method_version = "v1"

    def regions(self) -> list[str]:
        raw = os.getenv("INDEED_AI_REGIONS", "US,GB,DE").split(",")
        return [r.strip().upper() for r in raw if r.strip()]

    def since(self, metric_id: str, region: str) -> date:
        """Перший запуск - уся історія файлу; далі - як у каркасі (остання точка мінус LOOKBACK_DAYS)."""
        rows = self.db.select("fct_metric_values", "period_start",
                              eq={"metric_id": metric_id, "region": region}, limit=1)
        return super().since(metric_id, region) if rows else date.min

    def download(self) -> str:
        url = os.getenv("INDEED_AI_URL", DEFAULT_URL)
        return get_with_retry(url, headers=HEADERS, timeout=120).text

    def fetch_series(self) -> list[SeriesResult]:
        data = parse_ai_tracker_csv(self.download())   # не прочитався файл - впаде весь запуск
        out = []
        for cc in self.regions():
            res = SeriesResult(metric_id=METRIC_ID, region=cc)
            pts = data.get(cc)
            if not pts:
                res.error = f"у файлі немає країни {cc}"
            else:
                since = self.since(METRIC_ID, cc)
                res.points = [(d, v) for d, v in pts if d >= since]
                if not res.points:
                    res.error = f"немає значень з {since}"
            out.append(res)
        return out


if __name__ == "__main__":
    IndeedAiTracker().run()
