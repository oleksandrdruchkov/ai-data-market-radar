"""
collectors/adzuna_counts.py
Загальна кількість вакансій за пошуковим запитом Adzuna (поле count) -> fct_metric_values.

  adzuna_ml_count   запит «ml»  (за замовчуванням "machine learning engineer")
  adzuna_swe_count  запит «swe» (за замовчуванням "software developer")
  adzuna_ml_share   ml / swe, з numerator і denominator у рядку

На відміну від collectors/jobs_adzuna.py (перша сторінка оголошень для аналізу навичок),
тут береться лише одне число на ринок і запит: results_per_page=1, нас цікавить count.
Значення - знімок на дату запуску (UTC). Пропущений день лишається пропуском.

Зміна запитів змінює зміст ряду: тоді підніміть method_version (ADZUNA_COUNT_METHOD).

Змінні: ADZUNA_APP_ID, ADZUNA_APP_KEY (ті самі, що для jobs_adzuna)
        ADZUNA_COUNT_MARKETS="us,gb,de"
        ADZUNA_COUNT_QUERY_ML="machine learning engineer"
        ADZUNA_COUNT_QUERY_SWE="software developer"
        ADZUNA_COUNT_METHOD="v1"
Запуск: python -m collectors.adzuna_counts
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, date

from core.http import get_with_retry, redact  # noqa: F401  (redact - для тестів і помилок)
from collectors._metric_series import MetricSeriesCollector, SeriesResult

API = "https://api.adzuna.com/v1/api/jobs/{cc}/search/1"


def parse_count(payload: dict) -> int:
    """Чиста функція: count з відповіді Adzuna. Без count - помилка, а не нуль."""
    if not isinstance(payload, dict) or "count" not in payload:
        raise ValueError(f"У відповіді Adzuna немає count: {str(payload)[:200]}")
    n = int(payload["count"])
    if n < 0:
        raise ValueError(f"Від'ємний count: {n}")
    return n


def share_series(ml: SeriesResult, swe: SeriesResult) -> SeriesResult:
    """Чиста функція: частка ml/swe на ту саму дату. Помилка будь-якого ряду або swe=0 - помилка частки."""
    res = SeriesResult(metric_id="adzuna_ml_share", region=ml.region)
    if ml.error or swe.error:
        res.error = "немає одного з рядів: " + "; ".join(e for e in (ml.error, swe.error) if e)
        return res
    (d1, n_ml), (d2, n_swe) = ml.points[0], swe.points[0]
    if d1 != d2:
        res.error = f"різні дати рядів: {d1} і {d2}"
    elif n_swe <= 0:
        res.error = "знаменник swe = 0"
    else:
        res.points = [(d1, round(n_ml / n_swe, 6))]
        res.extra = {d1: {"numerator": n_ml, "denominator": n_swe}}
    return res


class AdzunaCounts(MetricSeriesCollector):
    source = "adzuna_counts"
    collector_version = "1"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.method_version = os.getenv("ADZUNA_COUNT_METHOD", "v1").strip() or "v1"

    def count(self, cc: str, query: str) -> int:
        app_id = os.getenv("ADZUNA_APP_ID", "").strip()
        app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            raise RuntimeError("Не задано ADZUNA_APP_ID / ADZUNA_APP_KEY")
        resp = get_with_retry(API.format(cc=cc),
                            params={"app_id": app_id, "app_key": app_key, "results_per_page": 1,
                                    "what": query, "content-type": "application/json"},
                            timeout=20)
        return parse_count(resp.json())

    def fetch_series(self) -> list[SeriesResult]:
        today: date = datetime.now(timezone.utc).date()
        queries = {
            "adzuna_ml_count": os.getenv("ADZUNA_COUNT_QUERY_ML", "machine learning engineer"),
            "adzuna_swe_count": os.getenv("ADZUNA_COUNT_QUERY_SWE", "software developer"),
        }
        out = []
        for cc in [c.strip().lower() for c in os.getenv("ADZUNA_COUNT_MARKETS", "us,gb,de").split(",") if c.strip()]:
            per = {}
            for metric_id, q in queries.items():
                res = SeriesResult(metric_id=metric_id, region=cc.upper())
                try:
                    res.points = [(today, float(self.count(cc, q)))]
                except Exception as e:
                    res.error = redact(f"{cc}/{q!r}: {type(e).__name__}: {e}")
                per[metric_id] = res
                out.append(res)
            out.append(share_series(per["adzuna_ml_count"], per["adzuna_swe_count"]))
        return out


if __name__ == "__main__":
    AdzunaCounts().run()
