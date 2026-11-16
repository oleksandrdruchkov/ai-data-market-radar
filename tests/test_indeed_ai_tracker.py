"""Indeed AI Tracker: розбір CSV і вибір дати початку - без бази."""

from __future__ import annotations

from datetime import date

import pytest

from collectors import indeed_ai_tracker as t

CSV = ("﻿date,jobcountry,AI_share_postings\n"
       "2019-01-02,US,1.80\n"
       "2019-01-01,US,1.75\n"
       "2019-01-01,GB,2.10\n"
       "2019-01-03,US,\n")


def test_parse_groups_sorts_and_skips_gaps():
    data = t.parse_ai_tracker_csv(CSV)
    assert data["US"] == [(date(2019, 1, 1), 1.75), (date(2019, 1, 2), 1.80)]   # порожнє - пропуск, не нуль
    assert data["GB"] == [(date(2019, 1, 1), 2.10)]


def test_parse_rejects_bad_files():
    with pytest.raises(ValueError):
        t.parse_ai_tracker_csv("<html>404</html>")
    with pytest.raises(ValueError):
        t.parse_ai_tracker_csv("date,jobcountry,value\n2019-01-01,US,1\n")      # немає *_share
    with pytest.raises(ValueError):
        t.parse_ai_tracker_csv("date,jobcountry,AI_share\n")                      # жодного рядка
    with pytest.raises(ValueError):
        t.parse_ai_tracker_csv("date,jobcountry,AI_share\n2019-01-01,US,140\n")   # не відсоток


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return self.rows


def make(rows, monkeypatch):
    c = t.IndeedAiTracker.__new__(t.IndeedAiTracker)
    c.db = FakeDb(rows)
    monkeypatch.setattr(c, "download", lambda: CSV)
    return c


def test_first_run_takes_whole_history(monkeypatch):
    monkeypatch.setenv("INDEED_AI_REGIONS", "us,de")
    res = {r.region: r for r in make([], monkeypatch).fetch_series()}
    assert res["US"].points[0] == (date(2019, 1, 1), 1.75)
    assert res["DE"].error and not res["DE"].points                           # немає країни - помилка, без підстановки


def test_all_countries_of_the_file_by_default(monkeypatch):
    monkeypatch.delenv("INDEED_AI_REGIONS", raising=False)
    res = {r.region: r for r in make([], monkeypatch).fetch_series()}
    assert set(res) == {"US", "GB"} and not res["GB"].error                     # усі країни файлу

    monkeypatch.setenv("INDEED_AI_EXCLUDE", "gb")
    assert [r.region for r in make([], monkeypatch).fetch_series()] == ["US"]
