"""
collectors/_metric_series.py
Каркас для збирачів, що пишуть готові часові ряди прямо в fct_metric_values
(FRED, лічильники Adzuna). BaseCollector тут не підходить: він розрахований на
окремі об'єкти (вакансія, стаття) з raw_items і колонками source/raw_item_id,
яких у fct_metric_values немає.

Підклас реалізує лише fetch_series() -> список SeriesResult.
Каркас робить:
  * інкрементне завантаження: since() дає дату, з якої просити дані
    (остання записана мінус LOOKBACK_DAYS - щоб підхопити уточнення джерела);
  * upsert у fct_metric_values по (metric_id, period_start, region);
  * журнал ops_collector_runs і перевірки якості core/quality.

Правило чесності: ряд, який не вдалося отримати, не пишеться взагалі.
Ніяких «останнє відоме значення» чи підставних чисел - лише помилка в журналі.

Лічильники в журналі: seen = рядів запитано, failed = рядів з помилкою,
new = записано точок. Так перевірка «обсяг різко змінився» порівнює кількість
рядів, а не кількість точок (перший запуск тягне всю історію, наступні - кілька днів).
"""

from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.db import Db
from core import quality

LOOKBACK_DAYS = 30
DEFAULT_BACKFILL_START = "2019-01-01"   # з запасом до корекції 2022 року - для перевірки індексу


@dataclass
class SeriesResult:
    metric_id: str
    region: str
    points: list[tuple[date, float]] = field(default_factory=list)   # (дата, значення)
    error: str | None = None
    extra: dict[date, dict] = field(default_factory=dict)            # numerator/denominator тощо


class MetricSeriesCollector:
    source: str = ""
    collector_version: str = "1"
    method_version: str = "v1"

    def __init__(self, db: Db | None = None):
        if not self.source:
            raise TypeError(f"{type(self).__name__}: задайте source")
        self.db = db or Db()
        self.log = logging.getLogger(f"radar.{self.source}")

    # ---------- реалізує підклас ----------

    def fetch_series(self) -> list[SeriesResult]:
        raise NotImplementedError

    # ---------- допоміжне ----------

    def since(self, metric_id: str, region: str) -> date:
        """З якої дати просити дані: остання записана - LOOKBACK_DAYS, або початок бекфілу."""
        rows = self.db.select("fct_metric_values", "period_start",
                              eq={"metric_id": metric_id, "region": region},
                              order="period_start", desc=True, limit=1)
        if rows:
            last = date.fromisoformat(str(rows[0]["period_start"])[:10])
            return last - timedelta(days=LOOKBACK_DAYS)
        return date.fromisoformat(os.getenv("METRIC_BACKFILL_START", DEFAULT_BACKFILL_START))

    def to_rows(self, s: SeriesResult, run_id) -> list[dict]:
        rows = []
        for d, v in s.points:
            row = {"metric_id": s.metric_id, "region": s.region,
                   "period_start": d.isoformat(), "period_end": d.isoformat(),
                   "value": v, "is_estimate": False,
                   "method_version": self.method_version, "run_id": run_id}
            row.update(s.extra.get(d, {}))
            rows.append(row)
        return rows

    # ---------- запуск ----------

    def run(self) -> dict:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.log.info(f"=== START {self.source} ===")
        run_id = self.db.start_run(self.source, self.collector_version)
        stats = {"seen": 0, "new": 0, "updated": 0, "failed": 0, "deferred": 0, "closed": 0}
        fetch_error: str | None = None
        errors: list[str] = []

        try:
            results = self.fetch_series()
        except Exception as e:
            self.log.exception(f"fetch_series() впав: {e}")
            results, fetch_error = [], f"{type(e).__name__}: {e}"

        stats["seen"] = len(results)
        for s in results:
            if s.error:
                stats["failed"] += 1
                errors.append(f"{s.metric_id}/{s.region}: {s.error}")
                self.log.warning(f"{s.metric_id}/{s.region}: {s.error}")
                continue
            rows = self.to_rows(s, run_id)
            if not rows:
                continue
            try:
                self.db.upsert("fct_metric_values", rows, on_conflict="metric_id,period_start,region")
                stats["new"] += len(rows)
                self.log.info(f"{s.metric_id}/{s.region}: {len(rows)} точок, "
                              f"остання {s.points[-1][0]} = {s.points[-1][1]}")
            except Exception as e:
                stats["failed"] += 1
                errors.append(f"{s.metric_id}/{s.region}: запис у БД: {e}")
                self.log.exception(f"Запис {s.metric_id}/{s.region} у БД впав")

        # Усі ряди впали - це те саме, що джерело не відповіло
        if not fetch_error and results and stats["failed"] == len(results):
            fetch_error = "; ".join(errors)[:2000]
        if fetch_error:
            status = "failed"
        elif stats["failed"]:
            status = "partial"
        else:
            status = "ok"
        self.db.finish_run(run_id, status, stats, fetch_error or ("; ".join(errors)[:2000] or None))

        alerts = quality.run_checks(self.db, self.source, run_id, stats, status, fetch_error)
        self.log.info(f"=== FINISH {self.source}: {status} | {stats} ===")
        if any(a["severity"] == "critical" for a in alerts) and quality.fail_on_critical():
            sys.exit(1)
        return stats
