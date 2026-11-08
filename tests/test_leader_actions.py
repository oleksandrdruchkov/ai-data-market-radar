"""Коло дій моделей-лідерів: лише підтверджені дані, рівна вага моделей, інтервал Вільсона."""

import subprocess

import pytest

from tests.pgdb import PgDb
from tests.test_framework import ROOT, ARGS, needs_pg


@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_c", "-c", "CREATE DATABASE radar_c"],
                   check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_c"]
    for f in ["tests/sql/legacy_schema.sql", "sql/001_core_framework.sql",
              "sql/005_leader_actions.sql", "sql/005_leader_actions.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    return PgDb(dbargs)


@needs_pg
def test_only_verified_rows_reach_the_circle(db):
    assert db.select("v_leader_action_circle") == []
    assert len(db.select("v_leader_action_pending")) == 2

    db.update("fct_leader_action_rates", {"verified": True}, eq={"lab": "Anthropic"})
    team = db.select("v_leader_action_circle")[0]
    assert team["n_models"] == 1 and abs(float(team["out_share"]) - 13 / 886) < 1e-9
    m = db.select("v_leader_action_models")[0]
    assert 0.0085 < float(m["ci_low"]) < 0.0087 and 0.0248 < float(m["ci_high"]) < 0.0250

    db.update("fct_leader_action_rates", {"verified": True}, eq={"lab": "OpenAI"})
    team = db.select("v_leader_action_circle")[0]
    assert team["n_models"] == 2
    assert abs(float(team["out_share"]) - (13 / 886 + 0.0027) / 2) < 1e-9     # рівна вага моделей
    assert abs(float(team["out_share"]) + float(team["in_share"]) - 1) < 1e-12  # коло = 100%


@needs_pg
def test_latest_model_per_lab_and_constraints(db):
    db.insert("fct_leader_action_rates", {
        "lab": "Anthropic", "model_name": "Older", "release_date": "2025-01-01", "source_doc": "x",
        "source_url": "u", "method": "internal_use_sample", "unit": "use", "rate_out": 0.5, "verified": True})
    db.update("fct_leader_action_rates", {"verified": True}, eq={"model_name": "Claude Mythos 5"})
    models = db.select("v_leader_action_models")
    assert [m["model_name"] for m in models] == ["Claude Mythos 5"]          # старіша модель не входить
    with pytest.raises(RuntimeError):                                       # тести-пастки заборонені схемою
        db.insert("fct_leader_action_rates", {
            "lab": "X", "model_name": "Y", "release_date": "2026-01-01", "source_doc": "d",
            "source_url": "u", "method": "trap_test", "unit": "use", "rate_out": 0.1})
