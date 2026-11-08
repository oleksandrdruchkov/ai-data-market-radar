"""
collectors/epoch_horizons.py
Горизонти автономності METR і Epoch Capabilities Index з архіву Epoch AI
(benchmark_data.zip, CC BY 4.0). Замінює collector_horizons.py.

Два збирачі з одним завантаженням архіву:
  * MetrHorizons -> fct_autonomy_horizons (source='METR', metric T50/T80, години)
    Для кожної моделі береться оцінка METR Time Horizon 1.1, а якщо її немає - TH1;
    серед рівних - вища. Один сирий запис = усі виміри однієї моделі для однієї метрики.
  * EpochEci     -> fct_capability_index (source='EPOCH_ECI', пункти індексу)

Інші джерела в fct_autonomy_horizons (UK AISI, Redwood ...) збирач не чіпає:
upsert іде лише по source='METR'.

Вказуйте джерело: METR via Epoch AI; Epoch AI, Capabilities & benchmarking (CC BY 4.0).

Змінні: EPOCH_ZIP_URL (за замовчуванням офіційний), EPOCH_ZIP_PATH (локальний файл, пріоритет)
Запуск: python -m collectors.epoch_horizons
"""

from __future__ import annotations

import io
import os
import re
import sys
import math
import zipfile
import logging
from functools import lru_cache

import pandas as pd
import requests

from core import BaseCollector, RawItem, Skip

log = logging.getLogger("radar.epoch")

EPOCH_ZIP_URL = "https://epoch.ai/data/benchmark_data.zip"
METR_CSV = "metr_time_horizons_external.csv"
ECI_CSV = "eci_scores.csv"
METR_URL = "https://epoch.ai/benchmarks/metr-time-horizons"
ECI_URL = "https://epoch.ai/benchmarks/eci"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
V11 = "METR-Horizon-v1.1"
MINUTES_PER_HOUR = 60.0           # у файлі Epoch горизонти METR у ХВИЛИНАХ
METR_COLS = ["Model version", "Time horizon", "Release date", "Time Horizon (80%)",
             "CI_low", "CI_high", "METR version"]


# ---------------- архів ----------------

@lru_cache(maxsize=1)
def load_zip_bytes() -> bytes:
    path = os.getenv("EPOCH_ZIP_PATH", "").strip()
    if path:
        with open(path, "rb") as f:
            return f.read()
    url = os.getenv("EPOCH_ZIP_URL", EPOCH_ZIP_URL).strip()
    log.info(f"Завантажую архів Epoch: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=90)
    resp.raise_for_status()
    return resp.content


def read_csv(zip_bytes: bytes, name: str, required: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        hits = [n for n in zf.namelist() if os.path.basename(n) == name]
        if not hits:
            raise RuntimeError(f"В архіві немає {name}")
        with zf.open(hits[0]) as fh:
            df = pd.read_csv(fh)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"У {name} немає колонок {missing}. Наявні: {list(df.columns)}")
    return df


def clean(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def hours(x):
    v = clean(x)
    return None if v is None or v <= 0 else round(v / MINUTES_PER_HOUR, 4)


def base_name(model: str) -> str:
    """claude-opus-4-6_unknown -> claude-opus-4-6; gpt-5-2025-08-07_high -> gpt-5-2025-08-07."""
    return re.sub(r"_(16k|unknown|low|medium|high|xhigh|max)$", "", str(model).strip(), flags=re.IGNORECASE)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> список dict без NaN (щоб лягло в jsonb)."""
    out = []
    for rec in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in rec.items()})
    return out


# ---------------- METR ----------------

class MetrHorizons(BaseCollector):
    source = "epoch_metr"
    fact_source = "METR"
    fact_table = "fct_autonomy_horizons"
    id_column = ""
    on_conflict = "source,metric,model_name"
    collection_method = "file"
    tracks_presence = False
    collector_version = "2"
    PICK_RULE = "metr_pick_v1"   # TH1.1 > TH1, серед рівних - вище значення

    def fetch(self):
        df = read_csv(load_zip_bytes(), METR_CSV, ["Model version", "Time horizon", "Release date"])
        cols = [c for c in METR_COLS if c in df.columns]
        df = df[cols].copy()
        df["_base"] = df["Model version"].map(base_name)
        no_date = sorted(df.loc[pd.to_datetime(df["Release date"], errors="coerce").isna(),
                                "Model version"].astype(str).unique())
        if no_date:
            self.log.warning(f"Без дати релізу (пропущено): {no_date}")
        for base, grp in df.groupby("_base"):
            rows = _records(grp.drop(columns="_base").sort_values("Model version"))
            for metric in ("T50", "T80"):
                yield RawItem(external_id=f"{metric}|{base}",
                              payload={"model": base, "metric": metric, "rows": rows})

    def parse(self, raw: RawItem) -> dict | None:
        p = raw.payload
        col = "Time horizon" if p["metric"] == "T50" else "Time Horizon (80%)"
        cand = []
        for r in p["rows"]:
            v = clean(r.get(col))
            d = pd.to_datetime(r.get("Release date"), errors="coerce")
            if v and v > 0 and not pd.isna(d):
                cand.append((str(r.get("METR version")) == V11, v, d, r))
        if not cand:
            raise Skip(f"{p['model']}: немає {p['metric']}")
        is_v11, v, d, r = max(cand, key=lambda t: (t[0], t[1]))
        is_t50 = p["metric"] == "T50"
        return {
            "metric": p["metric"],
            "model_name": p["model"],
            "release_date": d.date().isoformat(),
            "event_date": d.date().isoformat(),
            "value_hours": hours(v),
            "ci_low": hours(r.get("CI_low")) if is_t50 else None,
            "ci_high": hours(r.get("CI_high")) if is_t50 else None,
            "source_url": METR_URL,
            "is_synthetic": False,
            "extraction_method": "rule",
            "prompt_version": self.PICK_RULE,
        }


# ---------------- ECI ----------------

class EpochEci(BaseCollector):
    source = "epoch_eci"
    fact_source = "EPOCH_ECI"
    fact_table = "fct_capability_index"
    id_column = ""
    on_conflict = "source,model_name"
    collection_method = "file"
    tracks_presence = False
    collector_version = "2"

    def fetch(self):
        df = read_csv(load_zip_bytes(), ECI_CSV, ["Model", "eci", "date"])
        keep = [c for c in ["Model", "Display name", "Organization", "eci", "eci_ci_low",
                            "eci_ci_high", "date"] if c in df.columns]
        for rec in _records(df[keep]):
            yield RawItem(external_id=str(rec["Model"]).strip(), payload=rec)

    def parse(self, raw: RawItem) -> dict | None:
        r = raw.payload
        d = pd.to_datetime(r.get("date"), errors="coerce")
        eci = clean(r.get("eci"))
        if pd.isna(d) or eci is None:
            raise Skip(f"{r.get('Model')}: немає дати або ECI")
        return {
            "model_name": str(r["Model"]).strip(),
            "display_name": str(r.get("Display name") or r["Model"]).strip(),
            "release_date": d.date().isoformat(),
            "event_date": d.date().isoformat(),
            "eci": round(eci, 3),
            "ci_low": clean(r.get("eci_ci_low")),
            "ci_high": clean(r.get("eci_ci_high")),
            "organization": r.get("Organization"),
            "source_url": ECI_URL,
            "extraction_method": "rule",
            "prompt_version": "eci_v1",
        }


def main() -> int:
    code = 0
    # METR першим: збій ECI не втрачає вже збережені горизонти
    for cls in (MetrHorizons, EpochEci):
        try:
            cls().run()
        except SystemExit as e:
            code = max(code, int(e.code or 0))
    return code


if __name__ == "__main__":
    sys.exit(main())
