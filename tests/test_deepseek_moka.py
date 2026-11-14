"""Розбір сторінки вакансій DeepSeek на MokaHR - без мережі й бази."""

from __future__ import annotations

import json
import html

import pytest

from collectors import jobs_deepseek as ds


def page(jobs, total):
    state = {"org": {"id": "high-flyer"}, "jobs": jobs, "jobStats": {"orgId": "high-flyer", "total": total}}
    return f'<html><div data-x="{html.escape(json.dumps(state, ensure_ascii=False))}"></div></html>'


JOBS = [
    {"id": "a1", "title": "深度学习研究员", "status": "open", "openedAt": "2026-11-05T16:00:00.000Z",
     "description": "<p>负责 <b>大模型</b> 预训练</p>", "locations": [{"address": "北京"}, {"address": "杭州"}]},
    {"id": "b2", "title": "数据分析师", "status": "closed", "createdAt": "2026-11-06T08:49:03.000Z"},
    {"id": "c3", "title": "运维", "createdAt": "2026-10-01T00:00:00.000Z", "city": "杭州",
     "zhineng": {"id": 16427, "label": "运维"}, "commitment": "全职"},
    {"id": "d4", "title": "研究员", "locations": [{"address": "融科资讯中心C座", "cityName": "北京"}]},
]


def test_parse_page_open_jobs_and_total():
    jobs, total = ds.parse_page(page(JOBS, 3))
    assert total == 3 and [j["id"] for j in jobs] == ["a1", "c3", "d4"]     # закрита відкинута
    a = jobs[0]
    assert a["description"] == "负责 大模型 预训练" and a["location"] == "北京 / 杭州"
    assert a["posted_date"] == "2026-11-05" and a["url"].endswith("#/job/a1")
    assert jobs[1]["location"] == "杭州" and jobs[1]["description"] == "职能：运维；类型：全职"
    assert jobs[2]["location"] == "北京"                                         # місто, а не адреса


def test_changed_format_is_an_error():
    with pytest.raises(ValueError):
        ds.embedded_state("<html>no state</html>")
