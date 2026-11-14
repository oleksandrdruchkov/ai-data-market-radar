"""Лічильники arXiv: запит, розбір відповіді, проходження місяців - без мережі й бази."""

from __future__ import annotations

from datetime import date

import pytest

from collectors import arxiv_counts as ac

FEED = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        '<opensearch:totalResults>{n}</opensearch:totalResults></feed>')


def test_parse_total():
    assert ac.parse_total(FEED.format(n=1234)) == 1234
    with pytest.raises(ValueError):
        ac.parse_total('<feed xmlns="http://www.w3.org/2005/Atom"></feed>')   # немає числа - помилка, не 0
    with pytest.raises(ValueError):
        ac.parse_total("<html>")


def test_build_query_and_months():
    q = ac.build_query(date(2026, 2, 1), ["AI scientist", "self-improving"])
    assert "cat:cs.AI OR cat:cs.LG" in q
    assert '(ti:"AI scientist" OR abs:"AI scientist" OR ti:"self-improving" OR abs:"self-improving")' in q
    assert q.endswith("submittedDate:[202602010000 TO 202602282359]")
    assert "abs:" not in ac.build_query(date(2026, 2, 1), None)
    assert ac.months_between(date(2025, 11, 1), date(2026, 2, 14)) == [
        date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return self.rows


VER = f"{ac.METHOD_VERSION}-{ac.fingerprint(ac.DIRECTIONS)}"


def make(rows, answers, today=date(2026, 11, 14)):
    c = ac.ArxivCounts.__new__(ac.ArxivCounts)
    c.db, c.today, c._calls, c.sleep = FakeDb(rows), today, 0, lambda s: None
    c.directions, c.method_version = ac.DIRECTIONS, VER
    c.log = __import__("logging").getLogger("test")
    c.count = lambda q: answers(q)
    return c


def test_incremental_two_months_and_shares():
    res = {r.metric_id: r for r in make([{"period_start": "2026-10-01", "method_version": VER}],
                                        lambda q: 100 if "abs:" not in q else 25).fetch_series()}
    tot = res["arxiv_papers_total"]
    assert [d for d, _ in tot.points] == [date(2026, 10, 1), date(2026, 11, 1)]
    assert tot.extra[date(2026, 11, 1)]["is_estimate"] is True          # поточний місяць неповний
    sh = res["arxiv_share_agents"]
    assert sh.points[0] == (date(2026, 10, 1), 25.0)
    assert sh.extra[date(2026, 10, 1)]["numerator"] == 25.0 and sh.extra[date(2026, 10, 1)]["denominator"] == 100.0


def test_failed_total_blocks_shares():
    def answers(q):
        raise ValueError("arXiv впав")
    res = make([{"period_start": "2026-10-01", "method_version": VER}], answers).fetch_series()
    assert all(r.error for r in res)                                    # нічого не пишеться


def test_failure_mid_backfill_keeps_whole_months_only():
    calls = {"n": 0}

    def answers(q):
        calls["n"] += 1
        if calls["n"] > 8:                                               # 1-й місяць (6 запитів) цілий, 2-й обірвано
            raise RuntimeError("429")
        return 100 if "abs:" not in q else 10
    c = make([], answers)
    res = {r.metric_id: r for r in c.fetch_series()}
    assert [d for d, _ in res["arxiv_papers_total"].points] == [date(2023, 1, 1)]
    assert all(len(r.points) == 1 and not r.error for r in res.values())
    assert "429" in c.stop_reason


def test_query_budget_and_resume(monkeypatch):
    monkeypatch.setenv("ARXIV_COUNTS_MAX_QUERIES", "13")              # вистачає на 2 місяці по 6 запитів
    c = make([], lambda q: 50)
    res = {r.metric_id: r for r in c.fetch_series()}
    assert len(res["arxiv_papers_total"].points) == 2 and "ліміт" in c.stop_reason
    resumed = make([{"period_start": "2023-02-01", "method_version": VER}], lambda q: 1)
    assert resumed.since("arxiv_papers_total", "GLOBAL") == date(2023, 2, 1)


def test_phrase_report_counts_each_phrase():
    rows = ac.phrase_report(date(2026, 10, 1), count=lambda q: 10, out=lambda s: None)
    n_phrases = sum(len(p) for _, _, p in ac.DIRECTIONS.values())
    assert len(rows) == 1 + len(ac.DIRECTIONS) + n_phrases
    only = ac.phrase_report(date(2026, 10, 1), count=lambda q: 10, out=lambda s: None, only="robots")
    assert len(only) == 2 + len(ac.DIRECTIONS["robots"][2])


def test_phrase_report_stops_with_partial_result():
    seen = {"n": 0}

    def count(q):
        seen["n"] += 1
        if seen["n"] > 3:
            raise RuntimeError("429")
        return 10
    printed = []
    rows = ac.phrase_report(date(2026, 10, 1), count=count, out=printed.append)
    assert len(rows) == 3 and printed[-1].startswith("ЗУПИНЕНО")


def test_no_bare_ambiguous_words():
    for _, _, phrases in ac.DIRECTIONS.values():
        assert "oversight" not in phrases and "alignment" not in phrases


def test_changed_phrase_list_recomputes_history():
    c = make([{"period_start": "2026-10-01", "method_version": "v1-oldlist"}], lambda q: 1)
    assert c.since("arxiv_papers_total", "GLOBAL") == date(2023, 1, 1)


def test_merge_phrases_and_fingerprint():
    extra = [{"direction": "agents", "phrase": "agent swarm"},          # вже є - дубль
             {"direction": "agents", "phrase": "Agent Economy"},
             {"direction": "nope", "phrase": "x"}, {"direction": "safety", "phrase": " "}]
    merged = ac.merge_phrases(ac.DIRECTIONS, extra)
    assert merged["agents"][2].count("agent swarm") == 1 and "Agent Economy" in merged["agents"][2]
    assert "nope" not in merged
    assert ac.fingerprint(merged) != ac.fingerprint(ac.DIRECTIONS)
    assert ac.fingerprint(ac.merge_phrases(ac.DIRECTIONS, [])) == ac.fingerprint(ac.DIRECTIONS)
    assert "Agent Economy" not in ac.DIRECTIONS["agents"][2]              # код не змінюється
