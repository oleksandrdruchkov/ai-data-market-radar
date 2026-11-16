"""Відкриті вакансії китайських лабораторій: розбір лічильників і сума - без мережі й бази."""

from __future__ import annotations

import json
import html
from datetime import date

import pytest

from collectors import cn_lab_jobs as c
from collectors._metric_series import SeriesResult

DAY = date(2026, 11, 16)


def moka_page(state: dict) -> str:
    return f"<script>window.__data = '{html.escape(json.dumps(state))}'</script>"


def test_moka_total():
    assert c.moka_total(moka_page({"jobs": [], "jobStats": {"orgId": "moonshot", "total": 106}})) == 106
    with pytest.raises(ValueError):
        c.moka_total(moka_page({"jobs": []}))                      # немає лічильника - не нуль
    with pytest.raises(ValueError):
        c.moka_total("<html>captcha</html>")


def test_feishu_count():
    assert c.feishu_count({"code": 0, "data": {"count": 110, "job_post_list": []}}) == 110
    assert c.feishu_count({"code": 0, "data": {"count": 0}}) == 0
    with pytest.raises(ValueError):
        c.feishu_count({"code": -9000003, "message": "site not exist", "data": None})
    with pytest.raises(ValueError):
        c.feishu_count({"code": 0, "data": {}})


def lab(key, n=None, error=None):
    s = SeriesResult(metric_id=c.metric_id(key), region="CN")
    if error:
        s.error = error
    else:
        s.points = [(DAY, float(n))]
    return s


def test_total_only_when_all_labs_answered():
    ok = c.total_series([lab("deepseek", 36), lab("moonshot", 106), lab("minimax", 110)], ["a", "b", "c"])
    assert ok.points == [(DAY, 252.0)] and ok.extra[DAY] == {"denominator": 3}
    bad = c.total_series([lab("deepseek", 36), lab("moonshot", error="timeout")], ["a", "b"])
    assert bad.error and not bad.points                            # без підстановки пропущеної лабораторії
    assert c.total_series([], []).error


def test_collector_series_and_method_version(monkeypatch):
    monkeypatch.setenv("CN_LAB_JOBS", "moonshot,deepseek")
    col = c.CnLabJobs.__new__(c.CnLabJobs)
    col.keys = c.CnLabJobs.lab_keys()
    monkeypatch.setattr(col, "count", lambda key: {"moonshot": 106, "deepseek": 36}[key])
    res = {s.metric_id: s for s in col.fetch_series()}
    assert res["cn_lab_jobs_moonshot"].points[0][1] == 106
    assert res["cn_labs_open_jobs"].points[0][1] == 142
    monkeypatch.delenv("CN_LAB_JOBS")
    assert c.CnLabJobs.lab_keys() == ["deepseek", "moonshot", "zhipu", "minimax"]
    monkeypatch.setenv("CN_LAB_JOBS", "moonshot,unknown")
    with pytest.raises(ValueError):
        c.CnLabJobs.lab_keys()
