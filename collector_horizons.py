"""
collector_horizons.py
Збір вимірів горизонту автономності моделей (METR time horizons)
та запис у Supabase таблицю fct_autonomy_horizons.

Змінні середовища (GitHub Secrets, як у collector_arxiv.py):
  SUPABASE_URL, SUPABASE_KEY   (ключ із правом запису)
Необов'язково:
  METR_REPORT      звіт METR (за замовчуванням time-horizon-1-1)
  METR_FITS_URL    інший URL CSV з логістичними фітами
  METR_FITS_CSV    локальний шлях до CSV (пріоритетніший за URL)
  METR_DATES_URL   інший URL release_dates.yaml
"""

import os
import re
import io
import math
import logging
from datetime import date, datetime

import pandas as pd
import requests
import yaml
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Відсутні обов'язкові змінні SUPABASE_URL або SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLE = "fct_autonomy_horizons"
REPO = "METR/eval-analysis-public"
REPORT = os.getenv("METR_REPORT", "time-horizon-1-1").strip()
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
FITS_URL = os.getenv(
    "METR_FITS_URL",
    f"{RAW}/reports/{REPORT}/data/wrangled/logistic_fits/headline.csv"
).strip()
DATES_URL = os.getenv("METR_DATES_URL", f"{RAW}/data/external/release_dates.yaml").strip()
FITS_LOCAL = os.getenv("METR_FITS_CSV", "").strip()
SOURCE_URL = f"https://github.com/{REPO}"

HEADERS = {
    "User-Agent": "MarketRadarBot/1.0 (https://github.com/oleksandrdruchkov/ai-data-market-radar; contact@marketradar.local)",
}

# METR фіттить логістичну криву по log2(human_minutes), тому p50/p80 у ХВИЛИНАХ.
# Звірте топ-5 у логах з metr.org і за потреби змініть коефіцієнт.
MINUTES_PER_HOUR = 60.0

METRICS = {
    # metric: (колонка значення, нижня межа CI, верхня межа CI)
    "T50": ("p50", "p50q0.025", "p50q0.975"),
    "T80": ("p80", "p80q0.025", "p80q0.975"),
}


def norm(s) -> str:
    """Нормалізація назви моделі для зіставлення з release_dates.yaml."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def fetch_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def load_fits() -> pd.DataFrame:
    if FITS_LOCAL:
        logging.info(f"Читаю локальний CSV: {FITS_LOCAL}")
        return pd.read_csv(FITS_LOCAL)
    try:
        logging.info(f"Завантажую фіти METR: {FITS_URL}")
        return pd.read_csv(io.StringIO(fetch_text(FITS_URL)))
    except requests.HTTPError as e:
        raise RuntimeError(
            f"Не вдалося завантажити {FITS_URL}: {e}. "
            "Файл logistic_fits/*.csv є виходом DVC-пайплайна і може не лежати в репозиторії. "
            "Згенеруйте його (dvc repro у reports/<report>) та вкажіть METR_FITS_CSV або METR_FITS_URL."
        ) from e


def to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(str(value)).date()
    except Exception:
        return None


def load_release_dates() -> dict:
    logging.info(f"Завантажую дати релізів: {DATES_URL}")
    data = yaml.safe_load(fetch_text(DATES_URL))
    # Структура може бути {date: {модель: YYYY-MM-DD}} або {модель: YYYY-MM-DD}
    if isinstance(data, dict) and isinstance(data.get("date"), dict):
        data = data["date"]
    if not isinstance(data, dict):
        raise RuntimeError(
            "Невідомий формат release_dates.yaml - перегляньте файл і підправте load_release_dates()."
        )
    out = {}
    for k, v in data.items():
        d = to_date(v)
        if d:
            out[norm(k)] = d
    logging.info(f"Дат релізу зчитано: {len(out)}")
    return out


def clean(x):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def build_rows(fits: pd.DataFrame, dates: dict) -> list:
    if "agent" not in fits.columns:
        raise RuntimeError(f"У CSV немає колонки 'agent'. Наявні колонки: {list(fits.columns)}")

    rows, unmatched = [], set()
    for _, r in fits.iterrows():
        agent = str(r["agent"])
        released = dates.get(norm(agent))
        if released is None:
            unmatched.add(agent)
            continue
        for metric, (val_c, lo_c, hi_c) in METRICS.items():
            if val_c not in fits.columns:
                continue
            val = clean(r.get(val_c))
            if val is None or val <= 0:
                continue
            lo, hi = clean(r.get(lo_c)), clean(r.get(hi_c))
            rows.append({
                "source": "METR",
                "metric": metric,
                "model_name": agent,
                "release_date": released.isoformat(),
                "value_hours": round(val / MINUTES_PER_HOUR, 4),
                "ci_low": round(lo / MINUTES_PER_HOUR, 4) if lo else None,
                "ci_high": round(hi / MINUTES_PER_HOUR, 4) if hi else None,
                "source_url": SOURCE_URL,
                "is_synthetic": False,
            })
    if unmatched:
        logging.warning(f"Без дати релізу (пропущено): {sorted(unmatched)}")
    return rows


def run_horizons_pipeline():
    logging.info("=== START METR HORIZONS INGESTION ===")

    fits = load_fits()
    dates = load_release_dates()
    rows = build_rows(fits, dates)

    if not rows:
        logging.error(
            "Жодного рядка для запису - перевірте назви колонок CSV і збіг назв моделей з release_dates.yaml."
        )
        return

    top = sorted((r for r in rows if r["metric"] == "T50"), key=lambda r: -r["value_hours"])[:5]
    logging.info("Топ-5 T50 (години) для звірки з metr.org:")
    for r in top:
        logging.info(f"  {r['model_name']}: {r['value_hours']} h ({r['release_date']})")

    saved_count = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        res = (
            supabase.table(TABLE)
            .upsert(batch, on_conflict="source,metric,model_name")
            .execute()
        )
        saved_count += len(res.data) if res.data else len(batch)

    logging.info(f"Успішно збережено/оновлено {saved_count} рядків у {TABLE}.")


if __name__ == "__main__":
    run_horizons_pipeline()
