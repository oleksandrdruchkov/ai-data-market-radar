"""Лідер лабораторії = найвищий ECI серед моделей з підтвердженими даними."""

import subprocess

import pytest

from tests.pgdb import PgDb
from tests.test_framework import ROOT, ARGS, needs_pg


@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_e", "-c", "CREATE DATABASE radar_e"],
                   check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_e"]
    for f in ["tests/sql/legacy_schema.sql", "tests/sql/horizons_schema.sql", "sql/001_core_framework.sql",
              "sql/004_autonomy_horizons.sql", "sql/005_leader_actions.sql", "sql/006_system_cards_auto.sql",
              "sql/007_leader_by_eci.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    d = PgDb(dbargs)
    d.sql("DELETE FROM fct_leader_action_rates")
    return d


def add_rate(db, lab, model, release, rate):
    db.insert("fct_leader_action_rates", {
        "lab": lab, "model_name": model, "release_date": release, "source_doc": model, "source_url": "u",
        "method": "internal_use_sample", "unit": "use", "rate_out": rate, "verified": True, "verified_by": "auto"})


def add_eci(db, model, org, eci, display=None):
    db.insert("fct_capability_index", {"source": "EPOCH_ECI", "model_name": model, "display_name": display,
                                       "release_date": "2026-09-01", "eci": eci, "organization": org})


@needs_pg
def test_strongest_by_eci_not_newest(db):
    add_rate(db, "Anthropic", "Claude Mythos 5.1", "2026-09-01", 0.010)
    add_rate(db, "Anthropic", "Claude Opus 5.5", "2026-09-22", 0.002)      # новіша, але слабша
    add_eci(db, "claude-mythos-5-1_high", "Anthropic", 171.0)
    add_eci(db, "claude-opus-5-5", "Anthropic", 165.0)
    m = db.select("v_leader_action_models")[0]
    assert m["model_name"] == "Claude Mythos 5.1" and m["leader_basis"] == "eci"
    assert float(m["eci"]) == 171.0 and m["lab_top_model"] == "claude-mythos-5-1_high"


@needs_pg
def test_strongest_without_data_is_reported(db):
    add_rate(db, "OpenAI", "GPT-5.6 Sol", "2026-06-26", 0.0027)
    add_eci(db, "gpt-5-6-sol", "OpenAI", 160.0)
    add_eci(db, "gpt-6-astra", "OpenAI", 175.0, display="GPT-6 Astra")   # найсильніша, але без даних
    m = db.select("v_leader_action_models")[0]
    assert m["model_name"] == "GPT-5.6 Sol"
    assert m["lab_top_model"] == "GPT-6 Astra" and float(m["lab_top_eci"]) == 175.0


@needs_pg
def test_fallback_to_newest_without_eci(db):
    add_rate(db, "xAI", "Grok 4.20", "2026-04-07", 0.01)
    add_rate(db, "xAI", "Grok 4.6", "2026-08-12", 0.02)
    m = db.select("v_leader_action_models")[0]
    assert m["model_name"] == "Grok 4.6" and m["leader_basis"] == "newest" and m["eci"] is None
