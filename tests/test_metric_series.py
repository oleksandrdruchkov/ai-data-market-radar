"""
Збирачі рядів для індексу крихкості: FRED і лічильники Adzuna.
Чисті функції - без бази; наскрізні - на локальному Postgres (RADAR_TEST_PG).
"""

from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from collectors import fred_series, adzuna_counts
from collectors._metric_series import SeriesResult, LOOKBACK_DAYS
from tests.pgdb import PgDb, pg_args

ROOT = Path(__file__).resolve().parents[1]
ARGS = pg_args()
needs_pg = pytest.mark.skipif(ARGS is None, reason="RADAR_TEST_PG не задано")

CSV_NEW = "observation_date,DGS10\n2026-11-04,4.10\n2026-11-05,.\n2026-11-06,\n2026-11-07,4.15\n"
CSV_OLD = "﻿DATE,DFF\n2026-11-01,3.88\n"


# ---------------- чисті функції ----------------

def test_parse_fred_csv_skips_gaps():
    pts = fred_series.parse_fred_csv(CSV_NEW, "DGS10")
    assert pts == [(date(2026, 11, 4), 4.10), (date(2026, 11, 7), 4.15)]   # «.» і порожнє - пропуск, не нуль
    assert fred_series.parse_fred_csv(CSV_OLD, "DFF") == [(date(2026, 11, 1), 3.88)]


def test_parse_fred_csv_rejects_wrong_series_and_html():
    with pytest.raises(ValueError):
        fred_series.parse_fred_csv(CSV_NEW, "DFF")
    with pytest.raises(ValueError):
        fred_series.parse_fred_csv("<html>error</html>", "DGS10")


def test_indeed_series_ids():
    assert fred_series.indeed_series(["us", " GB", ""]) == [
        ("indeed_softdev_postings", "US", "IHLIDXUSTPSOFTDEVE"),
        ("indeed_total_postings", "US", "IHLIDXUS"),
        ("indeed_softdev_postings", "GB", "IHLIDXGBTPSOFTDEVE"),
        ("indeed_total_postings", "GB", "IHLIDXGB"),
    ]


def test_parse_count():
    assert adzuna_counts.parse_count({"count": 1234, "results": []}) == 1234
    with pytest.raises(ValueError):
        adzuna_counts.parse_count({"results": []})            # немає count - помилка, не 0


def test_share_series():
    d = date(2026, 11, 9)
    ml = SeriesResult("adzuna_ml_count", "US", [(d, 50.0)])
    swe = SeriesResult("adzuna_swe_count", "US", [(d, 200.0)])
    s = adzuna_counts.share_series(ml, swe)
    assert s.points == [(d, 0.25)] and s.extra[d] == {"numerator": 50.0, "denominator": 200.0}
    assert adzuna_counts.share_series(ml, SeriesResult("adzuna_swe_count", "US", error="x")).error
    assert adzuna_counts.share_series(ml, SeriesResult("adzuna_swe_count", "US", [(d, 0.0)])).error


def test_redact(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_KEY", "secret123")
    assert "secret123" not in adzuna_counts.redact("for url: https://x?app_key=secret123")


# ---------------- наскрізні ----------------

@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_test_ms",
                    "-c", "CREATE DATABASE radar_test_ms"], check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_test_ms"]
    for f in ["tests/sql/legacy_schema.sql", "sql/001_core_framework.sql", "sql/011_bubble_metrics.sql",
              "sql/012_baa10y.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    return PgDb(dbargs)


@pytest.fixture(autouse=True)
def no_exit(monkeypatch):
    monkeypatch.setenv("RADAR_FAIL_ON_CRITICAL", "0")


class FakeFred(fred_series.FredSeries):
    def __init__(self, db, csvs: dict[str, str]):
        super().__init__(db=db)
        self.csvs, self.asked = csvs, {}

    def series(self):
        return [("fred_ust10y", "US", "DGS10"), ("fred_fed_funds", "US", "DFF")]

    def download(self, sid, since):
        self.asked[sid] = since
        if sid not in self.csvs:
            raise RuntimeError("404 Not Found")
        return self.csvs[sid]


@needs_pg
def test_fred_incremental_and_partial(db):
    # 1. Обидва ряди є
    stats = FakeFred(db, {"DGS10": CSV_NEW, "DFF": CSV_OLD.replace("DATE", "observation_date")}).run()
    assert stats["seen"] == 2 and stats["failed"] == 0 and stats["new"] == 3
    rows = db.select("fct_metric_values", eq={"metric_id": "fred_ust10y"}, order="period_start")
    assert [float(r["value"]) for r in rows] == [4.10, 4.15]
    assert all(r["region"] == "US" and r["period_start"] == r["period_end"] for r in rows)

    # 2. Другий запуск просить лише хвіст; DFF впав - його старі дані не чіпаються, нових не вигадано
    f = FakeFred(db, {"DGS10": CSV_NEW})
    stats = f.run()
    assert f.asked["DGS10"] == date(2026, 11, 7) - timedelta(days=LOOKBACK_DAYS)
    assert stats["failed"] == 1
    run = db.select("ops_collector_runs", eq={"source": "fred_series"}, order="run_id", desc=True, limit=1)[0]
    assert run["status"] == "partial" and "DFF" in run["error"]
    assert len(db.select("fct_metric_values", eq={"metric_id": "fred_fed_funds"})) == 1

    # 3. Усе впало -> failed, нічого не записано
    stats = FakeFred(db, {}).run()
    run = db.select("ops_collector_runs", eq={"source": "fred_series"}, order="run_id", desc=True, limit=1)[0]
    assert run["status"] == "failed"
    alerts = db.select("ops_quality_alerts", eq={"run_id": run["run_id"]})
    assert any(a["severity"] == "critical" for a in alerts)


@needs_pg
def test_adzuna_counts_writes_share(db, monkeypatch):
    monkeypatch.setenv("ADZUNA_COUNT_MARKETS", "us,gb")
    counts = {("us", "machine learning engineer"): 500, ("us", "software developer"): 10000,
              ("gb", "software developer"): 4000}

    class Fake(adzuna_counts.AdzunaCounts):
        def count(self, cc, q):
            if (cc, q) not in counts:
                raise RuntimeError("503")
            return counts[(cc, q)]

    stats = Fake(db=db).run()
    assert stats["seen"] == 6 and stats["failed"] == 2       # GB ml і GB share
    share = db.select("fct_metric_values", eq={"metric_id": "adzuna_ml_share"})
    assert len(share) == 1 and share[0]["region"] == "US"
    assert float(share[0]["value"]) == 0.05
    assert float(share[0]["numerator"]) == 500 and float(share[0]["denominator"]) == 10000
    assert db.select("fct_metric_values", eq={"metric_id": "adzuna_ml_count", "region": "GB"}) == []


@needs_pg
def test_migration_metadata(db):
    m = {r["metric_id"]: r for r in db.select("dim_metrics")}
    assert m["adzuna_ml_share"]["denominator_def"] == "adzuna_swe_count"
    assert m["fred_ig_oas"]["topic"] == "bubble" and m["indeed_softdev_postings"]["topic"] == "shared"
    assert m["vacancies_new"]["topic"] == "radar"
    assert m["fred_baa10y"]["topic"] == "bubble"
    assert ("fred_baa10y", "US", "BAA10Y") in fred_series.FIXED
    src = {r["source"] for r in db.select("ops_sources")}
    assert {"fred_series", "adzuna_counts"} <= src
