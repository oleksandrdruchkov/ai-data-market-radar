"""
collector_horizons.py
Збір вимірів горизонту автономності моделей (METR time horizons)
та запис у Supabase таблицю fct_autonomy_horizons.

Джерело: Epoch AI Capabilities & Benchmarking Hub, файл metr_time_horizons_external.csv
з архіву benchmark_data.zip (дані METR, ліцензія CC BY 4.0).
Вказуйте джерело: METR via Epoch AI.

Що пишемо:
  METR / T50 (з довірчим інтервалом) та METR / T80 (де є), години.
  Для кожної моделі береться оцінка METR Time Horizon 1.1, а якщо її немає,
  то оригінальна оцінка TH1 (Measuring AI Ability to Complete Long Tasks).

Змінні середовища (GitHub Secrets, як у collector_arxiv.py):
  SUPABASE_URL, SUPABASE_KEY   (ключ із правом запису)
Необов'язково:
  EPOCH_ZIP_URL    URL архіву (за замовчуванням офіційний)
  EPOCH_ZIP_PATH   локальний шлях до ZIP (пріоритетніший за URL)
"""

import os
import io
import re
import math
import zipfile
import logging

import pandas as pd
import requests
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
EPOCH_ZIP_URL = os.getenv("EPOCH_ZIP_URL", "https://epoch.ai/data/benchmark_data.zip").strip()
EPOCH_ZIP_PATH = os.getenv("EPOCH_ZIP_PATH", "").strip()
METR_CSV_NAME = "metr_time_horizons_external.csv"
SOURCE_URL = "https://epoch.ai/benchmarks/metr-time-horizons"

HEADERS = {
    "User-Agent": "MarketRadarBot/1.0 (https://github.com/oleksandrdruchkov/ai-data-market-radar; contact@marketradar.local)",
}

# У файлі Epoch значення в ХВИЛИНАХ (перевірено: claude-mythos-preview-early = 1044.8 хв = 17.4 год).
MINUTES_PER_HOUR = 60.0

REQUIRED_COLS = ["Model version", "Time horizon", "Release date"]
V11 = "METR-Horizon-v1.1"


def load_zip_bytes() -> bytes:
    if EPOCH_ZIP_PATH:
        logging.info(f"Читаю локальний ZIP: {EPOCH_ZIP_PATH}")
        with open(EPOCH_ZIP_PATH, "rb") as f:
            return f.read()
    logging.info(f"Завантажую архів Epoch: {EPOCH_ZIP_URL}")
    response = requests.get(EPOCH_ZIP_URL, headers=HEADERS, timeout=90)
    response.raise_for_status()
    return response.content


def read_metr_csv(zip_bytes: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if os.path.basename(n) == METR_CSV_NAME]
        if not names:
            raise RuntimeError(
                f"В архіві немає {METR_CSV_NAME}. Файли METR в архіві: "
                f"{[n for n in zf.namelist() if 'metr' in n.lower()]}"
            )
        with zf.open(names[0]) as fh:
            df = pd.read_csv(fh)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise RuntimeError(f"У {METR_CSV_NAME} немає колонок {missing}. Наявні: {list(df.columns)}")
    logging.info(f"{METR_CSV_NAME}: {len(df)} рядків")
    return df


def base_name(model: str) -> str:
    """claude-opus-4-6_unknown -> claude-opus-4-6; gpt-5-2025-08-07_high -> gpt-5-2025-08-07."""
    return re.sub(r"_(16k|unknown|low|medium|high|xhigh|max)$", "", str(model).strip(), flags=re.IGNORECASE)


def clean(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def hours(x):
    v = clean(x)
    return None if v is None or v <= 0 else round(v / MINUTES_PER_HOUR, 4)


def build_rows(df: pd.DataFrame) -> list:
    d = df.copy()
    d["release_dt"] = pd.to_datetime(d["Release date"], errors="coerce")
    d["t50"] = pd.to_numeric(d["Time horizon"], errors="coerce")
    d["t80"] = pd.to_numeric(d["Time Horizon (80%)"], errors="coerce") if "Time Horizon (80%)" in d.columns else float("nan")
    d["ci_lo"] = pd.to_numeric(d["CI_low"], errors="coerce") if "CI_low" in d.columns else float("nan")
    d["ci_hi"] = pd.to_numeric(d["CI_high"], errors="coerce") if "CI_high" in d.columns else float("nan")
    d["is_v11"] = d["METR version"].astype(str).eq(V11) if "METR version" in d.columns else False
    d["base"] = d["Model version"].map(base_name)

    no_date = sorted(d.loc[d["release_dt"].isna(), "Model version"].astype(str).unique())
    if no_date:
        logging.warning(f"Без дати релізу (пропущено): {no_date}")
    d = d[d["release_dt"].notna() & (d["t50"] > 0)]

    rows = []
    for base, grp in d.groupby("base"):
        # TH1.1 має пріоритет; серед рівних береться вище значення
        best = grp.sort_values(["is_v11", "t50"], ascending=[False, False]).iloc[0]
        released = best["release_dt"].date().isoformat()

        rows.append({
            "source": "METR", "metric": "T50", "model_name": base,
            "release_date": released, "value_hours": hours(best["t50"]),
            "ci_low": hours(best["ci_lo"]), "ci_high": hours(best["ci_hi"]),
            "source_url": SOURCE_URL, "is_synthetic": False,
        })

        g80 = grp[grp["t80"] > 0]
        if not g80.empty:
            b80 = g80.sort_values(["is_v11", "t80"], ascending=[False, False]).iloc[0]
            rows.append({
                "source": "METR", "metric": "T80", "model_name": base,
                "release_date": b80["release_dt"].date().isoformat(), "value_hours": hours(b80["t80"]),
                "ci_low": None, "ci_high": None,
                "source_url": SOURCE_URL, "is_synthetic": False,
            })
    return rows


def run_horizons_pipeline():
    logging.info("=== START METR HORIZONS INGESTION (via Epoch AI) ===")

    df = read_metr_csv(load_zip_bytes())
    rows = build_rows(df)
    if not rows:
        raise RuntimeError("Жодного рядка для запису - перевірте вміст metr_time_horizons_external.csv.")

    t50 = sorted((r for r in rows if r["metric"] == "T50"), key=lambda r: -r["value_hours"])[:5]
    logging.info("Топ-5 T50 (години) для звірки з metr.org:")
    for r in t50:
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
