"""
collector_horizons.py
Збір вимірів із архіву Epoch AI benchmark_data.zip (дані METR та Epoch, CC BY 4.0)
і запис у Supabase:

  1) fct_autonomy_horizons - METR T50 (з довірчим інтервалом) та T80, у годинах.
     Для кожної моделі береться оцінка METR Time Horizon 1.1, а якщо її немає,
     то оригінальна оцінка TH1. Файл: metr_time_horizons_external.csv
  2) fct_capability_index  - Epoch Capabilities Index (ECI), загальна здатність
     моделі в пунктах індексу (не години). Файл: epoch_capabilities_index/eci_scores.csv

Вказуйте джерело: METR via Epoch AI; Epoch AI, Capabilities & benchmarking (CC BY 4.0).

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

TABLE_HORIZONS = "fct_autonomy_horizons"
TABLE_ECI = "fct_capability_index"
EPOCH_ZIP_URL = os.getenv("EPOCH_ZIP_URL", "https://epoch.ai/data/benchmark_data.zip").strip()
EPOCH_ZIP_PATH = os.getenv("EPOCH_ZIP_PATH", "").strip()
METR_CSV_NAME = "metr_time_horizons_external.csv"
ECI_CSV_NAME = "eci_scores.csv"
METR_SOURCE_URL = "https://epoch.ai/benchmarks/metr-time-horizons"
ECI_SOURCE_URL = "https://epoch.ai/benchmarks/eci"

HEADERS = {
    "User-Agent": "MarketRadarBot/1.0 (https://github.com/oleksandrdruchkov/ai-data-market-radar; contact@marketradar.local)",
}

# У файлі METR від Epoch значення в ХВИЛИНАХ (claude-mythos-preview-early = 1044.8 хв = 17.4 год).
MINUTES_PER_HOUR = 60.0
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


def read_csv_from_zip(zip_bytes: bytes, csv_name: str, required_cols: list) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if os.path.basename(n) == csv_name]
        if not names:
            raise RuntimeError(f"В архіві немає {csv_name}. Схожі файли: "
                               f"{[n for n in zf.namelist() if csv_name.split('_')[0] in n.lower()]}")
        with zf.open(names[0]) as fh:
            df = pd.read_csv(fh)
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"У {csv_name} немає колонок {missing}. Наявні: {list(df.columns)}")
    logging.info(f"{csv_name}: {len(df)} рядків")
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


def upsert_batches(table: str, rows: list, on_conflict: str) -> int:
    saved = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        res = supabase.table(table).upsert(batch, on_conflict=on_conflict).execute()
        saved += len(res.data) if res.data else len(batch)
    return saved


# ---------- METR horizons ----------

def build_horizon_rows(df: pd.DataFrame) -> list:
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
        rows.append({
            "source": "METR", "metric": "T50", "model_name": base,
            "release_date": best["release_dt"].date().isoformat(), "value_hours": hours(best["t50"]),
            "ci_low": hours(best["ci_lo"]), "ci_high": hours(best["ci_hi"]),
            "source_url": METR_SOURCE_URL, "is_synthetic": False,
        })
        g80 = grp[grp["t80"] > 0]
        if not g80.empty:
            b80 = g80.sort_values(["is_v11", "t80"], ascending=[False, False]).iloc[0]
            rows.append({
                "source": "METR", "metric": "T80", "model_name": base,
                "release_date": b80["release_dt"].date().isoformat(), "value_hours": hours(b80["t80"]),
                "ci_low": None, "ci_high": None,
                "source_url": METR_SOURCE_URL, "is_synthetic": False,
            })
    return rows


def run_horizons(zip_bytes: bytes):
    df = read_csv_from_zip(zip_bytes, METR_CSV_NAME, ["Model version", "Time horizon", "Release date"])
    rows = build_horizon_rows(df)
    if not rows:
        raise RuntimeError("Жодного рядка METR для запису - перевірте вміст metr_time_horizons_external.csv.")

    t50 = sorted((r for r in rows if r["metric"] == "T50"), key=lambda r: -r["value_hours"])[:5]
    logging.info("Топ-5 T50 (години) для звірки з metr.org:")
    for r in t50:
        logging.info(f"  {r['model_name']}: {r['value_hours']} h ({r['release_date']})")

    saved = upsert_batches(TABLE_HORIZONS, rows, "source,metric,model_name")
    logging.info(f"Успішно збережено/оновлено {saved} рядків у {TABLE_HORIZONS}.")


# ---------- Epoch Capabilities Index ----------

def build_eci_rows(df: pd.DataFrame) -> list:
    d = df.copy()
    d["release_dt"] = pd.to_datetime(d["date"], errors="coerce")
    d["eci_v"] = pd.to_numeric(d["eci"], errors="coerce")
    d = d[d["release_dt"].notna() & d["eci_v"].notna()]

    rows = []
    for _, r in d.iterrows():
        org = r.get("Organization")
        rows.append({
            "source": "EPOCH_ECI",
            "model_name": str(r["Model"]).strip(),
            "display_name": str(r.get("Display name", r["Model"])).strip(),
            "release_date": r["release_dt"].date().isoformat(),
            "eci": round(float(r["eci_v"]), 3),
            "ci_low": clean(r.get("eci_ci_low")),
            "ci_high": clean(r.get("eci_ci_high")),
            "organization": None if pd.isna(org) else str(org),
            "source_url": ECI_SOURCE_URL,
        })
    return rows


def run_eci(zip_bytes: bytes):
    df = read_csv_from_zip(zip_bytes, ECI_CSV_NAME, ["Model", "eci", "date"])
    rows = build_eci_rows(df)
    if not rows:
        raise RuntimeError("Жодного рядка ECI для запису - перевірте вміст eci_scores.csv.")

    top = sorted(rows, key=lambda r: -r["eci"])[:3]
    logging.info("Топ-3 ECI для звірки з epoch.ai:")
    for r in top:
        logging.info(f"  {r['display_name']}: {r['eci']} ({r['release_date']})")

    saved = upsert_batches(TABLE_ECI, rows, "source,model_name")
    logging.info(f"Успішно збережено/оновлено {saved} рядків у {TABLE_ECI}.")


def run_horizons_pipeline():
    logging.info("=== START EPOCH / METR INGESTION ===")
    zip_bytes = load_zip_bytes()

    # METR записується першим: збій ECI не втрачає вже збережені горизонти
    run_horizons(zip_bytes)
    run_eci(zip_bytes)


if __name__ == "__main__":
    run_horizons_pipeline()
