"""
collector_horizons.py
METR time horizons -> Supabase fct_autonomy_horizons

Env (GitHub Secrets, як у collector_arxiv.py):
  SUPABASE_URL, SUPABASE_KEY (потрібен ключ із правом запису)
Необов'язково:
  METR_REPORT     (за замовчуванням time-horizon-1-1)
  METR_FITS_URL   (інший URL CSV з логістичними фітами)
  METR_FITS_CSV   (локальний шлях до CSV; має пріоритет над URL)
  METR_DATES_URL  (інший URL release_dates.yaml)
"""
import os
import re
import sys
import math
from datetime import date, datetime

import pandas as pd
import requests
import yaml
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

REPO = "METR/eval-analysis-public"
REPORT = os.getenv("METR_REPORT", "time-horizon-1-1")
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
FITS_URL = os.getenv("METR_FITS_URL", f"{RAW}/reports/{REPORT}/data/wrangled/logistic_fits/headline.csv")
DATES_URL = os.getenv("METR_DATES_URL", f"{RAW}/data/external/release_dates.yaml")
FITS_LOCAL = os.getenv("METR_FITS_CSV")
SOURCE_URL = f"https://github.com/{REPO}"

# METR фіттить логістичну криву по log2(human_minutes), тому p50/p80 у ХВИЛИНАХ.
# Перевірте за друком топ-5 нижче (порівняйте з metr.org) і за потреби змініть.
MINUTES_PER_HOUR = 60.0

METRICS = {
    # metric: (колонка значення, нижня межа CI, верхня межа CI)
    "T50": ("p50", "p50q0.025", "p50q0.975"),
    "T80": ("p80", "p80q0.025", "p80q0.975"),
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def fetch_text(url: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def load_fits() -> pd.DataFrame:
    if FITS_LOCAL:
        print(f"Читаю локальний CSV: {FITS_LOCAL}")
        return pd.read_csv(FITS_LOCAL)
    try:
        print(f"Завантажую {FITS_URL}")
        txt = fetch_text(FITS_URL)
    except requests.HTTPError as e:
        sys.exit(
            f"Не вдалося завантажити {FITS_URL}: {e}\n"
            "Файл logistic_fits/*.csv є виходом DVC-пайплайна і може не лежати в репозиторії. "
            "Згенеруйте його (dvc repro у reports/<report>) або вкажіть METR_FITS_CSV / METR_FITS_URL."
        )
    from io import StringIO
    return pd.read_csv(StringIO(txt))


def to_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.to_datetime(str(v)).date()
    except Exception:
        return None


def load_release_dates() -> dict:
    data = yaml.safe_load(fetch_text(DATES_URL))
    # структура файлу може бути {date: {model: YYYY-MM-DD}} або {model: YYYY-MM-DD}
    if isinstance(data, dict) and isinstance(data.get("date"), dict):
        data = data["date"]
    if not isinstance(data, dict):
        sys.exit("Невідомий формат release_dates.yaml - перегляньте файл і підправте load_release_dates().")
    out = {}
    for k, v in data.items():
        d = to_date(v)
        if d:
            out[norm(k)] = d
    print(f"Дат релізу: {len(out)}")
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
        sys.exit(f"У CSV немає колонки 'agent'. Колонки: {list(fits.columns)}")

    rows, unmatched = [], set()
    for _, r in fits.iterrows():
        agent = str(r["agent"])
        rel = dates.get(norm(agent))
        if rel is None:
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
                "release_date": rel.isoformat(),
                "value_hours": round(val / MINUTES_PER_HOUR, 4),
                "ci_low": round(lo / MINUTES_PER_HOUR, 4) if lo else None,
                "ci_high": round(hi / MINUTES_PER_HOUR, 4) if hi else None,
                "source_url": SOURCE_URL,
                "is_synthetic": False,
            })
    if unmatched:
        print(f"Без дати релізу (пропущено): {sorted(unmatched)}")
    return rows


def main():
    fits = load_fits()
    dates = load_release_dates()
    rows = build_rows(fits, dates)
    if not rows:
        sys.exit("Жодного рядка для запису - перевірте назви колонок і збіг назв моделей з release_dates.yaml.")

    t50 = sorted([r for r in rows if r["metric"] == "T50"], key=lambda r: -r["value_hours"])[:5]
    print("Топ-5 T50 (години) для звірки з metr.org:")
    for r in t50:
        print(f"  {r['model_name']}: {r['value_hours']} h ({r['release_date']})")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    for i in range(0, len(rows), 100):
        supabase.table("fct_autonomy_horizons").upsert(
            rows[i:i + 100], on_conflict="source,metric,model_name"
        ).execute()
    print(f"Записано рядків: {len(rows)}")


if __name__ == "__main__":
    main()
