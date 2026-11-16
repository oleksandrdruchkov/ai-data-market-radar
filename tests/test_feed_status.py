"""Плитка «Стан збору даних»: зведення свіжості джерел."""

from metrics.feed import feed_status


def row(source, freshness, hours=0.2, last_status="ok", enabled=True):
    return {"source": source, "freshness": freshness, "hours_since_ok": hours,
            "last_status": last_status, "is_enabled": enabled}


def test_all_fresh_and_monthly_source_not_run_yet():
    s = feed_status([row("adzuna", "fresh", 0.3), row("arxiv", "fresh", 0.1),
                     row("phrase_candidates", "never_ok", None, last_status=None)])
    assert s["level"] == "ok" and (s["fresh"], s["total"]) == (2, 2)
    assert s["never"] == ["phrase_candidates"] and s["hours"] == 0.1


def test_problems_change_level():
    rows = [row("a", "fresh"), row("b", "fresh"), row("c", "fresh"), row("d", "failing", 30)]
    s = feed_status(rows)
    assert s["level"] == "warn" and s["problems"] == [("d", "failing", 30.0)] and s["total"] == 4
    s = feed_status([row("a", "fresh"), row("b", "stale", 90), row("c", "failing", 5)])
    assert s["level"] == "bad" and s["problems"][0] == ("b", "stale", 90.0)      # застарілі - першими
    assert feed_status([row("a", "stale", 100)])["level"] == "bad"


def test_never_ok_after_failed_run_is_a_problem():
    s = feed_status([row("a", "fresh"), row("b", "fresh"), row("new", "never_ok", None, last_status="failed")])
    assert s["level"] == "warn" and s["problems"] == [("new", "failing", None)] and s["never"] == []


def test_disabled_and_empty():
    s = feed_status([row("a", "fresh"), row("off", "disabled", 500, enabled=False)])
    assert s["level"] == "ok" and s["total"] == 1
    assert feed_status([])["level"] == "unknown" and feed_status(None)["level"] == "unknown"
