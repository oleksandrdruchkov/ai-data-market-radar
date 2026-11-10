"""
collectors/fred_series.py
Ряди FRED для індексу крихкості бульбашки ШІ -> fct_metric_values.

  fred_ig_oas             BAMLC0A0CM     спред інвестиційного рівня, %        (US)
  fred_hy_oas             BAMLH0A0HYM2   спред високодохідних облігацій, %    (US)
  fred_baa10y             BAA10Y         спред Moody's Baa над 10-річними, %  (US, історія з 1986)
  fred_ust10y             DGS10          дохідність 10-річних облігацій, %    (US)
  fred_fed_funds          DFF            ефективна ставка ФРС, %              (US)
  indeed_softdev_postings IHLIDX{CC}TPSOFTDEVE  вакансії розробників, індекс  (US, GB, DE)
  indeed_total_postings   IHLIDX{CC}            усі вакансії, індекс          (US, GB, DE)

Джерело - публічний CSV FRED (fredgraph.csv), ключ API не потрібен.
Порожні значення FRED («.» у вихідні та свята) пропускаються, а не заповнюються.

Ліцензії: ряди ICE BofA і Moody's (спреди) мають обмеження на передрук - на публічному табло
показувати похідний бал індексу, а не сирі значення. Indeed: вказувати
«Indeed Hiring Lab via FRED».

Змінні: FRED_INDEED_REGIONS="US,GB,DE"   METRIC_BACKFILL_START="2019-01-01"
Запуск: python -m collectors.fred_series
"""

from __future__ import annotations

import io
import csv
import os
from datetime import date

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}

# (metric_id, region, FRED series id)
FIXED = [
    ("fred_ig_oas", "US", "BAMLC0A0CM"),
    ("fred_hy_oas", "US", "BAMLH0A0HYM2"),
    ("fred_baa10y", "US", "BAA10Y"),        # ICE - лише 3 роки; цей - для перевірки на 2022 році
    ("fred_ust10y", "US", "DGS10"),
    ("fred_fed_funds", "US", "DFF"),
]


def indeed_series(regions: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for cc in regions:
        cc = cc.strip().upper()
        if cc:
            out.append(("indeed_softdev_postings", cc, f"IHLIDX{cc}TPSOFTDEVE"))
            out.append(("indeed_total_postings", cc, f"IHLIDX{cc}"))
    return out


def parse_fred_csv(text: str, series_id: str) -> list[tuple[date, float]]:
    """Чиста функція. Перша колонка - дата (observation_date або DATE у старому форматі),
    друга - значення. Порожні та «.» пропускаються. Порожній результат - помилка."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise ValueError(f"{series_id}: неочікуваний формат CSV: {text[:120]!r}")
    if header[1].strip().upper() != series_id.upper():
        raise ValueError(f"{series_id}: у CSV інший ряд: {header}")
    points = []
    for row in reader:
        if len(row) < 2:
            continue
        raw = row[1].strip()
        if raw in ("", "."):
            continue
        points.append((date.fromisoformat(row[0].strip()[:10]), float(raw)))
    points.sort()
    return points


class FredSeries(MetricSeriesCollector):
    source = "fred_series"
    collector_version = "1"
    method_version = "v1"

    def series(self) -> list[tuple[str, str, str]]:
        regions = os.getenv("FRED_INDEED_REGIONS", "US,GB,DE").split(",")
        return FIXED + indeed_series(regions)

    def download(self, series_id: str, since: date) -> str:
        resp = get_with_retry(FRED_CSV, params={"id": series_id, "cosd": since.isoformat()},
                              headers=HEADERS, timeout=60)
        return resp.text

    def fetch_series(self) -> list[SeriesResult]:
        out = []
        for metric_id, region, sid in self.series():
            res = SeriesResult(metric_id=metric_id, region=region)
            try:
                since = self.since(metric_id, region)
                pts = parse_fred_csv(self.download(sid, since), sid)
                res.points = [(d, v) for d, v in pts if d >= since]
                if not res.points:
                    res.error = f"{sid}: немає значень з {since}"
            except Exception as e:
                res.error = f"{sid}: {type(e).__name__}: {e}"
            out.append(res)
        return out


if __name__ == "__main__":
    FredSeries().run()
