"""Сторінка перевірки (core/review.py) і правило «на коло лише реальне використання» (sql/013)."""

from __future__ import annotations

import pytest

from core import review
from tests.test_system_cards import db, needs_pg  # noqa: F401  (фікстура зі схемою 001-013)


def test_check_password():
    assert review.check_password("s3cret", "s3cret")
    assert not review.check_password("wrong", "s3cret")
    assert not review.check_password("", "")              # пароль не задано = вхід вимкнено
    assert not review.check_password("x", None)


def _row(db, model, method, verified=False, verified_by=None, rate=0.01):
    return db.insert("fct_leader_action_rates", {
        "lab": "Anthropic", "model_name": model, "release_date": "2026-09-01", "source_doc": model,
        "source_url": f"https://example/{model}.pdf", "method": method, "unit": "use",
        "n_total": 1000, "n_out": 10, "rate_out": rate, "verified": verified, "verified_by": verified_by,
        "verification_log": ["друга модель недоступна"]})[0]["id"]


@needs_pg
def test_queue_approve_reject_undo(db):
    real = _row(db, "Claude Real 1", "internal_use_sample")
    other = _row(db, "Claude Real 2", "internal_use_sample")
    sim = _row(db, "Claude Sim 1", "deployment_simulation")

    # у черзі - лише реальне використання
    assert {r["id"] for r in review.pending(db)} == {real, other}
    assert {r["id"] for r in db.select("v_leader_action_pending")} == {real, other}
    with pytest.raises(ValueError):
        review.approve(db, sim)                                  # симуляцію підтвердити не можна

    review.approve(db, real, "звірено зі с. 96")
    r = db.select("fct_leader_action_rates", eq={"id": real})[0]
    assert r["verified"] is True and r["verified_by"] == "human" and r["verified_at"]
    assert r["verification_log"][-1] == "Підтверджено людиною: звірено зі с. 96"

    with pytest.raises(ValueError):
        review.reject(db, other, "  ")                          # без причини не можна
    review.reject(db, other, "цитата не містить числа")
    r = db.select("fct_leader_action_rates", eq={"id": other})[0]
    assert r["verified"] is False and r["verified_by"] == "human" and "цитата" in r["notes"]

    assert review.pending(db) == []
    assert db.select("v_leader_action_pending") == []
    assert {r["id"] for r in review.decided(db)} == {real, other}
    # на колі: підтверджений реальний запис є, відхилений і симуляції - ні
    assert [m["model_name"] for m in db.select("v_leader_action_models")] == ["Claude Real 1"]

    review.undo(db, other)
    r = db.select("fct_leader_action_rates", eq={"id": other})[0]
    assert r["verified_by"] is None and r["verified_at"] is None
    assert [x["id"] for x in review.pending(db)] == [other]


@needs_pg
def test_verified_simulation_not_on_circle(db):
    _row(db, "GPT Sim", "deployment_simulation", verified=True, verified_by="auto")
    assert db.select("v_leader_action_models") == []
    assert db.select("v_leader_action_circle") == []
