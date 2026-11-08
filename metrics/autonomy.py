"""
metrics/autonomy.py
Показники горизонту автономності -> fct_metric_values (по місяцях, region='GLOBAL').

  autonomy_t50_frontier  найбільший METR T50 серед моделей, випущених до кінця місяця (години),
                         з межами довірчого інтервалу саме тієї моделі-рекордсменки;
  sai_t_frontier         SAI_T, % від еталона «1 людино-рік = 2 080 год».
                         Формула і стеля - у core/scales.py (спільні з табло app.py).

Чесність ряду:
  * рахуються лише справжні виміри (source='METR', is_synthetic = false);
  * ряд закінчується місяцем останнього виміру - після того, як METR перестав оновлюватись,
    рівна лінія «до сьогодні» не малюється;
  * значення понад стелю набору задач METR (16 год) позначаються is_estimate = true:
    інструмент там уже не вимірює надійно.

Запуск: python -m metrics.autonomy   (після collectors.epoch_horizons)
"""

from __future__ import annotations

import math
import sys
import logging
from datetime import date

from core.db import Db
from core.scales import INSTRUMENT_CEILING_H, beyond_ceiling
from core.scales import sai_t as _sai_t

log = logging.getLogger("radar.metrics.autonomy")

RUN_LABEL = "metrics_autonomy"
METHOD_VERSION = "v1"


def sai_t(hours: float | None) -> float | None:
    """Формула - у core/scales.py; тут лише округлення для запису в базу."""
    if hours is None:
        return None
    v = _sai_t(hours)
    return None if math.isnan(v) else round(v, 3)


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def months(first: date, last: date):
    cur = month_start(first)
    while cur <= last:
        yield cur
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)


def build_rows(measurements: list[dict]) -> list[dict]:
    """Чиста функція: виміри T50 -> рядки fct_metric_values для двох показників."""
    pts = []
    for m in measurements:
        v = m.get("value_hours")
        if v is None or float(v) <= 0 or not m.get("release_date"):
            continue
        pts.append((date.fromisoformat(str(m["release_date"])[:10]), float(v),
                    m.get("ci_low"), m.get("ci_high"), m["model_name"]))
    if not pts:
        return []
    pts.sort()

    rows, best, i = [], None, 0
    for ms in months(pts[0][0], pts[-1][0]):
        me = month_end(ms)
        while i < len(pts) and pts[i][0] <= me:
            if best is None or pts[i][1] > best[1]:
                best = pts[i]
            i += 1
        _, v, lo, hi, _model = best
        lo = float(lo) if lo is not None else None
        hi = float(hi) if hi is not None else None
        est = beyond_ceiling(v)
        base = {"period_start": ms.isoformat(), "period_end": me.isoformat(), "region": "GLOBAL",
                "is_estimate": est, "method_version": METHOD_VERSION}
        rows.append({**base, "metric_id": "autonomy_t50_frontier", "value": round(v, 4),
                     "lower_bound": lo, "upper_bound": hi})
        rows.append({**base, "metric_id": "sai_t_frontier", "value": sai_t(v),
                     "lower_bound": sai_t(lo), "upper_bound": sai_t(hi)})
    return rows


def run(db: Db | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db = db or Db()
    run_id = db.start_run(RUN_LABEL, METHOD_VERSION)
    try:
        meas = db.select("fct_autonomy_horizons", "model_name,release_date,value_hours,ci_low,ci_high",
                         eq={"source": "METR", "metric": "T50", "is_synthetic": False})
        rows = build_rows(meas)
        for r in rows:
            r["run_id"] = run_id
        if rows:
            db.upsert("fct_metric_values", rows, on_conflict="metric_id,period_start,region")
        stats = {"seen": len(meas), "new": len(rows)}
        db.finish_run(run_id, "ok" if rows else "failed", stats,
                      None if rows else "Немає вимірів METR T50")
        last = rows[-1] if rows else None
        log.info(f"Записано {len(rows)} значень з {len(meas)} вимірів; "
                 f"останній місяць: {last and last['period_start']} SAI_T={last and last['value']}%")
        return 0 if rows else 1
    except Exception as e:
        log.exception("Розрахунок показників упав")
        db.finish_run(run_id, "failed", {}, f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
