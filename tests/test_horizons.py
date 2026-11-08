"""Горизонти METR / ECI на каркасі і розрахунок показників."""

from __future__ import annotations

import io
import zipfile
import subprocess
from datetime import date

import pytest

from collectors import epoch_horizons as eh
from metrics import autonomy
from tests.pgdb import PgDb, pg_args
from tests.test_framework import ROOT, ARGS, needs_pg

METR = """Model version,Time horizon,Release date,Time Horizon (80%),CI_low,CI_high,METR version
gpt-4-0314,5.3,2023-03-14,1.1,3.0,9.0,METR-Horizon-v1
gpt-4-0314_high,6.0,2023-03-14,,4.0,9.5,METR-Horizon-v1.1
o3_high,92.0,2025-04-16,20.0,60.0,140.0,METR-Horizon-v1.1
o3_medium,120.0,2025-04-16,25.0,70.0,190.0,METR-Horizon-v1
claude-mythos-preview-early,1044.8,2026-04-07,250.0,600.0,2000.0,METR-Horizon-v1.1
nodate-model,10.0,,,,,METR-Horizon-v1.1
"""
ECI = """Model,Display name,Organization,eci,eci_ci_low,eci_ci_high,date
gpt-4-0314,GPT-4,OpenAI,120.5,118,123,2023-03-14
o3,o3,OpenAI,145.25,143,147,2025-04-16
broken,Broken,X,,,,2025-01-01
"""


def make_zip(tmp_path) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("benchmark_data/metr_time_horizons_external.csv", METR)
        z.writestr("benchmark_data/epoch_capabilities_index/eci_scores.csv", ECI)
    path = tmp_path / "bd.zip"
    path.write_bytes(buf.getvalue())
    return str(path)


@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_h",
                    "-c", "CREATE DATABASE radar_h"], check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_h"]
    for f in ["tests/sql/legacy_schema.sql", "tests/sql/horizons_schema.sql",
              "sql/001_core_framework.sql", "sql/004_autonomy_horizons.sql", "sql/004_autonomy_horizons.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    return PgDb(dbargs)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("RADAR_FAIL_ON_CRITICAL", "0")
    monkeypatch.setenv("EPOCH_ZIP_PATH", make_zip(tmp_path))
    eh.load_zip_bytes.cache_clear()


@needs_pg
def test_metr_eci_and_metrics(db):
    s = eh.MetrHorizons(db=db).run()
    # 4 базові моделі (з nodate) x 2 метрики; nodate і відсутні T80 - пропуски, не помилки
    assert s["seen"] == 8 and s["failed"] == 0 and s["skipped"] == 2
    h = {(r["metric"], r["model_name"]): r for r in db.select("fct_autonomy_horizons")}
    g = h[("T50", "gpt-4-0314")]
    assert float(g["value_hours"]) == 0.1 and g["extraction_method"] == "rule"   # TH1.1 (6 хв) має пріоритет
    assert g["first_seen_at"] is not None                                         # legacy-рядок оновлено
    assert float(h[("T50", "o3")]["value_hours"]) == round(92 / 60, 4)          # v1.1 важливіша за більше v1
    assert h[("T80", "gpt-4-0314")]["ci_low"] is None
    assert all(r["source"] == "METR" for r in h.values())

    s = eh.EpochEci(db=db).run()
    assert s["seen"] == 3 and s["skipped"] == 1
    e = {r["model_name"]: r for r in db.select("fct_capability_index")}
    assert float(e["o3"]["eci"]) == 145.25 and e["o3"]["source"] == "EPOCH_ECI"

    assert autonomy.run(db) == 0
    vals = db.select("fct_metric_values", eq={"metric_id": "sai_t_frontier"}, order="period_start")
    assert vals[0]["period_start"] == "2023-03-01" and vals[-1]["period_start"] == "2026-04-01"
    last = vals[-1]
    assert last["is_estimate"] is True                                  # 17.4 год > стелі 16 год
    assert abs(float(last["value"]) - autonomy.sai_t(1044.8 / 60)) < 1e-6
    series = db.select("v_metric_series", eq={"metric_id": "autonomy_t50_frontier"})
    assert len(series) == len(vals) and series[0]["unit"] == "hours"
    runs = {r["source"]: r["status"] for r in db.select("ops_collector_runs")}
    assert runs == {"epoch_metr": "ok", "epoch_eci": "ok", "metrics_autonomy": "ok"}


def test_build_rows_frontier_and_bounds():
    rows = autonomy.build_rows([
        {"model_name": "a", "release_date": "2024-01-10", "value_hours": 1.0, "ci_low": 0.5, "ci_high": 2.0},
        {"model_name": "b", "release_date": "2024-03-05", "value_hours": 0.5, "ci_low": 0.2, "ci_high": 0.9},
        {"model_name": "c", "release_date": "2024-03-20", "value_hours": 3.0, "ci_low": None, "ci_high": None},
    ])
    t50 = [r for r in rows if r["metric_id"] == "autonomy_t50_frontier"]
    assert [r["period_start"] for r in t50] == ["2024-01-01", "2024-02-01", "2024-03-01"]
    assert [r["value"] for r in t50] == [1.0, 1.0, 3.0]          # рекорд не падає, коли слабша модель виходить
    assert t50[1]["lower_bound"] == 0.5 and t50[2]["lower_bound"] is None
    assert autonomy.sai_t(2080) == 100.0                         # еталон = 100%


def test_month_helpers():
    assert autonomy.month_end(date(2024, 2, 10)) == date(2024, 2, 29)
    assert autonomy.month_end(date(2024, 12, 1)) == date(2024, 12, 31)
