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
    """Підставна база. Зважає на фільтр eq (лише за полями, які є в рядку), порядок і limit -
    як справжня: рядок іншої версії методу на запит за поточною версією не повертається."""

    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, eq=None, order=None, desc=False, limit=None, **k):
        rows = [r for r in self.rows
                if all(r[f] == v for f, v in (eq or {}).items() if f in r)]
        if order:
            rows = sorted(rows, key=lambda r: str(r.get(order) or ""), reverse=desc)
        return rows[:limit] if limit else rows


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
        if calls["n"] > 1 + len(ac.DIRECTIONS) + len(ac.GROUPS) + 2:     # 1-й місяць цілий, 2-й обірвано
            raise RuntimeError("429")
        return 100 if "abs:" not in q else 10
    c = make([], answers)
    res = {r.metric_id: r for r in c.fetch_series()}
    assert [d for d, _ in res["arxiv_papers_total"].points] == [date(2023, 1, 1)]
    assert all(len(r.points) == 1 and not r.error for r in res.values())
    assert "429" in c.stop_reason


def test_query_budget_and_resume(monkeypatch):
    per_month = 1 + len(ac.DIRECTIONS) + len(ac.GROUPS)
    monkeypatch.setenv("ARXIV_COUNTS_MAX_QUERIES", str(2 * per_month + 1))   # вистачає рівно на 2 місяці
    c = make([], lambda q: 50)
    res = {r.metric_id: r for r in c.fetch_series()}
    assert len(res["arxiv_papers_total"].points) == 2 and "ліміт" in c.stop_reason
    resumed = make([{"period_start": "2023-02-01", "method_version": VER}], lambda q: 1)
    assert resumed.since("arxiv_papers_total", "GLOBAL") == date(2023, 2, 1)


def test_phrase_report_counts_each_phrase():
    rows = ac.phrase_report(date(2026, 10, 1), count=lambda q: 10, out=lambda s: None)
    n_phrases = sum(len(p) for _, _, p, _ in ac.DIRECTIONS.values())
    assert len(rows) == 1 + 2 * len(ac.STEM_CHECKS) + len(ac.GROUPS) + len(ac.DIRECTIONS) + n_phrases
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
    for _, _, phrases, _ in ac.DIRECTIONS.values():
        labels = [ac.label(p).lower() for p in phrases]
        for bad in ("oversight", "alignment", "agentic", "scheming", "interpretability", "robot"):
            assert bad not in labels                                     # «robot» - лише в парі з моделлю ШІ
        assert len(set(labels)) == len(labels)


def test_and_phrase_and_groups():
    q = ac.build_query(date(2026, 10, 1), [(["robot", "humanoid"], ["LLM"])])
    assert '((ti:"robot" OR abs:"robot" OR ti:"humanoid" OR abs:"humanoid") AND (ti:"LLM" OR abs:"LLM"))' in q
    assert set(ac.GROUPS) == {g for *_, g in ac.DIRECTIONS.values()}
    res = {r.metric_id: r for r in make([], lambda q: 100 if "abs:" not in q else 5).fetch_series()}
    assert "arxiv_group_autonomy" in res and "arxiv_group_oversight" in res
    assert res["arxiv_group_oversight"].points[0][1] == 5.0


def test_long_group_query_goes_by_post(monkeypatch):
    calls = []
    monkeypatch.setattr(ac, "get_with_retry", lambda url, **k: calls.append(k.get("method", "GET")) or
                        type("R", (), {"text": FEED.format(n=7)})())
    c = ac.ArxivCounts.__new__(ac.ArxivCounts)
    c._calls, c.sleep = 0, lambda s: None
    long_q = ac.build_query(date(2026, 10, 1), ac.group_phrases(ac.DIRECTIONS, "autonomy"))
    assert c.count(long_q) == 7 and calls == ["POST"]
    c.count(ac.build_query(date(2026, 10, 1), None))
    assert calls[-1] == "GET"


def test_changed_phrase_list_recomputes_history():
    # у базі лише рядки старого списку фраз -> уся історія заново
    c = make([{"period_start": "2026-10-01", "method_version": "v1-oldlist"}], lambda q: 1)
    assert c.since("arxiv_papers_total", "GLOBAL") == date(2023, 1, 1)


def test_later_old_version_rows_do_not_restart_backfill():
    # Перерахунок новим списком дійшов до 2023-10, а пізніші місяці ще старої версії.
    # Збір має продовжитись з 2023-10, а не щоразу повертатись на 2023-01.
    c = make([{"period_start": "2023-10-01", "method_version": VER},
              {"period_start": "2024-05-01", "method_version": "v1-oldlist"}], lambda q: 1)
    assert c.since("arxiv_papers_total", "GLOBAL") == date(2023, 10, 1)


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


def test_custom_report():
    rows = ac.custom_report(date(2026, 10, 1), ["self-preservation", "shutdown resistance"],
                            count=lambda q: 4, out=lambda s: None)
    assert [r[0] for r in rows] == ["УСІ ФРАЗИ", "self-preservation", "shutdown resistance"]


def test_stop_signal_threshold():
    assert ac.stop_signal([], 3) == (False, 10)                         # мало статей - тиша
    assert ac.stop_signal([2, 3, 4], 12)[0] is True                     # 12 >= max(10, 3*3)
    assert ac.stop_signal([8] * 12, 12)[0] is False                     # поріг 24
    assert ac.stop_signal([8] * 12, 24)[0] is True


def test_stop_alert_only_for_last_complete_month():
    def answers(q):
        if "abs:" not in q:
            return 100
        jump = "shutdown resistance" in q and "20230201" in q            # стрибок лише в лютому
        return 15 if jump else 1
    c = make([], answers, today=date(2023, 3, 14))
    c.fetch_series()
    assert len(c.pending_alerts) == 1 and "2023-02" in c.pending_alerts[0]["message"]
