"""Коло лідерів за періодами (sql/027): минулий місяць - лише моделі, випущені до його кінця."""

import subprocess

import pytest

from tests.pgdb import PgDb
from tests.test_framework import ROOT, ARGS, needs_pg


@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_p", "-c", "CREATE DATABASE radar_p"],
                   check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_p"]
    # ролі Supabase, яким міграції 026-027 видають права на читання
    subprocess.run(["psql", *dbargs, "-q", "-c",
                    "DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
                    "-c", "DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$"],
                   check=True, capture_output=True)
    for f in ["tests/sql/legacy_schema.sql", "tests/sql/horizons_schema.sql", "sql/001_core_framework.sql",
              "sql/004_autonomy_horizons.sql", "sql/005_leader_actions.sql", "sql/006_system_cards_auto.sql",
              "sql/007_leader_by_eci.sql", "sql/008_cards_reprocess.sql", "sql/009_cards_queue_and_keys.sql",
              "sql/010_units_free.sql", "sql/013_real_use_only_and_review.sql",
              "sql/026_circle_units_aliases.sql", "sql/027_circle_periods.sql", "sql/027_circle_periods.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    d = PgDb(dbargs)
    d.sql("DELETE FROM fct_leader_action_rates")
    return d


def add_rate(db, lab, model, release, rate, unit):
    db.insert("fct_leader_action_rates", {
        "lab": lab, "model_name": model, "release_date": release, "source_doc": model, "source_url": "u",
        "method": "internal_use_sample", "unit": unit, "rate_out": rate, "verified": True, "verified_by": "human"})


def add_eci(db, model, org, eci, release):
    db.insert("fct_capability_index", {"source": "EPOCH_ECI", "model_name": model, "display_name": model,
                                       "release_date": release, "eci": eci, "organization": org})


def seed(db):
    add_rate(db, "Anthropic", "Claude Fable 5.1", "2026-09-01", 0.00022, "use")
    add_rate(db, "Anthropic", "Claude Mythos 5.2", "2026-11-01", 0.00032, "turn")   # = Claude Fable 5.2
    add_rate(db, "OpenAI", "GPT-6 Astra", "2026-09-03", 0.0006, "trajectory")
    add_eci(db, "Claude Fable 5.1", "Anthropic", 167.0, "2026-09-01")
    add_eci(db, "Claude Fable 5.2", "Anthropic", 173.4, "2026-11-09")
    add_eci(db, "GPT-6 Astra", "OpenAI", 169.0, "2026-09-03")


def models(db, period=None, current=False):
    rows = db.select("v_leader_action_models_monthly")
    return [r for r in rows if (r["is_current"] if current else str(r["period"]) == period)]


@needs_pg
def test_empty_without_verified_rows(db):
    for v in ("v_leader_action_models_monthly", "v_leader_action_circle_monthly",
              "v_leader_action_models", "v_leader_action_circle"):
        assert db.select(v) == []


@needs_pg
def test_past_month_uses_only_models_released_by_then(db):
    seed(db)
    assert models(db, "2026-08-01") == []                       # до першого запису періодів немає
    october = {m["lab"]: m for m in models(db, "2026-10-01")}
    assert october["Anthropic"]["model_name"] == "Claude Fable 5.1"
    assert october["Anthropic"]["lab_top_model"] == "Claude Fable 5.1"   # 5.2 ще не випущено
    assert october["OpenAI"]["model_name"] == "GPT-6 Astra"
    assert models(db, "2026-09-01") and not models(db, "2026-09-01")[0]["is_current"]

    now = {m["lab"]: m for m in models(db, current=True)}
    assert now["Anthropic"]["model_name"] == "Claude Fable 5.2"
    assert now["Anthropic"]["reported_as"] == "Claude Mythos 5.2" and now["Anthropic"]["unit"] == "turn"


@needs_pg
def test_current_views_equal_last_period(db):
    seed(db)
    cur = db.select("v_leader_action_models")
    last = models(db, current=True)
    assert [(m["lab"], m["model_name"], m["unit"]) for m in cur] == \
           [(m["lab"], m["model_name"], m["unit"]) for m in sorted(last, key=lambda m: (m["lab"], m["unit"]))]
    circle = db.select("v_leader_action_circle")
    assert {c["unit"] for c in circle} == {"turn", "trajectory"}
    assert "period" not in circle[0] and "period" not in cur[0]

    periods = db.select("v_leader_action_circle_monthly")
    assert sum(1 for p in periods if p["is_current"]) == len(circle)
    oct_units = {p["unit"] for p in periods if str(p["period"]) == "2026-10-01"}
    assert oct_units == {"use", "trajectory"}                   # різні одиниці не усереднюються
