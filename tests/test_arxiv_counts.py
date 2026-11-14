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


def make(rows, answers, today=date(2026, 11, 14)):
    c = ac.ArxivCounts.__new__(ac.ArxivCounts)
    c.db, c.today, c._calls, c.sleep = FakeDb(rows), today, 0, lambda s: None
    c.count = lambda q: answers(q)
    return c


def test_incremental_two_months_and_shares():
    res = {r.metric_id: r for r in make([{"period_start": "2026-10-01"}],
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
    res = make([{"period_start": "2026-10-01"}], answers).fetch_series()
    assert all(r.error for r in res)                                    # нічого не пишеться


def test_phrase_report_counts_each_phrase():
    asked = []
    rows = ac.phrase_report(date(2026, 10, 1), count=lambda q: asked.append(q) or 10)
    n_phrases = sum(len(p) for _, _, p in ac.DIRECTIONS.values())
    assert len(rows) == 1 + len(ac.DIRECTIONS) + n_phrases


def test_no_bare_ambiguous_words():
    for _, _, phrases in ac.DIRECTIONS.values():
        assert "oversight" not in phrases and "alignment" not in phrases
