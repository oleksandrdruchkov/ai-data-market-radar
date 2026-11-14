"""Кандидати у фрази напрямів ArXiv - без бази й мережі."""

from __future__ import annotations

import pytest

from collectors import arxiv_counts as ac
from metrics import arxiv_phrase_candidates as pc
from core import review

SIGNALS = [
    {"predicted_skill": "Test-Time Compute", "title": "Scaling thinking"},                  # уже ловиться
    {"predicted_skill": "Agent Economy", "title": "LLM agents trading with each other"},
    {"predicted_skill": "agent-economy", "title": "Markets of AI agents", "signal_summary": "agentic markets"},
    {"predicted_skill": "Quantum Error Correction", "title": "Better codes"},
    {"predicted_skill": "", "title": "no skill"},
]


def test_norm_and_covered():
    assert pc.norm("  Test-Time_Compute ") == "test time compute"
    assert pc.covered("Scalable test-time compute", ["test-time compute"])
    assert not pc.covered("Agent Economy", ["agent memory"])


def test_find_candidates_groups_and_guesses_direction():
    cands = pc.find_candidates(SIGNALS, ac.DIRECTIONS)
    assert [c["skill_norm"] for c in cands] == ["agent economy", "quantum error correction"]
    top = cands[0]
    assert top["n_signals"] == 2 and top["phrase"] in ("Agent Economy", "agent-economy")
    assert top["suggested_direction"] == "agents"          # у назвах «LLM agents», «AI agents»
    assert cands[1]["suggested_direction"] is None


class FakeDb:
    def __init__(self):
        self.updates = []

    def update(self, table, values, *, eq):
        self.updates.append((table, values, eq))


def test_decide_phrase_rules():
    db = FakeDb()
    review.decide_phrase(db, "agent economy", "added", "agents")
    assert db.updates[-1][1]["status"] == "added" and db.updates[-1][1]["direction"] == "agents"
    review.decide_phrase(db, "x", "rejected")
    assert db.updates[-1][1]["direction"] is None
    with pytest.raises(ValueError):
        review.decide_phrase(db, "x", "added", None)          # додати без напряму не можна
