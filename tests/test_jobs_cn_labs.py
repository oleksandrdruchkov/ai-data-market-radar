"""Вакансії китайських лабораторій: payload Feishu, факт вакансії, класи лабораторій - без мережі й бази."""

from __future__ import annotations

import pytest

from collectors import jobs_cn_labs as c
from collectors.jobs_deepseek import cn_vacancy_fact

FEISHU_JOB = {
    "id": "7449", "title": " 大模型算法工程师 ",
    "description": "<p>负责大模型预训练</p>", "requirement": "熟悉PyTorch&amp;CUDA",
    "city_info": {"name": "上海"}, "publish_time": 1763000000000,
    "job_category": {"name": "算法"}, "recruit_type": {"name": "全职"},
}


def test_feishu_payload():
    p = c.feishu_payload(FEISHU_JOB, "https://x.jobs.feishu.cn", "379481", "MiniMax")
    assert p["id"] == "7449" and p["title"] == "大模型算法工程师" and p["company"] == "MiniMax"
    assert p["description"] == "负责大模型预训练\n熟悉PyTorch&CUDA"          # теги й HTML-сутності прибрано
    assert p["location"] == "上海" and p["category"] == "算法 全职"
    assert p["posted_date"] == "2025-11-13"
    assert p["url"] == "https://x.jobs.feishu.cn/379481/position/7449/detail"
    bare = c.feishu_payload({"id": 1, "title": "x"}, "https://h", "p", "MiniMax")
    assert bare["posted_date"] is None and bare["location"] is None and bare["description"] == ""


def test_fact_is_china_and_keyword_based():
    p = c.feishu_payload(FEISHU_JOB, "https://x.jobs.feishu.cn", "379481", "MiniMax")
    f = cn_vacancy_fact(p, "MiniMax")
    assert f["region"] == "China" and f["country_code"] == "CN" and f["company"] == "MiniMax"
    assert f["title"] == f["title_original"] == "大模型算法工程师"            # без перекладу
    assert f["track"] == "Machine Learning" and f["extraction_method"] == "keywords:kw_v1"
    assert {s.name for s in f["_skills"]} >= {"LLM", "Pre-training", "PyTorch", "CUDA"}
    assert f["event_date"] == "2025-11-13"


class FakeResp:
    def __init__(self, body): self._b = body
    def raise_for_status(self): pass
    def json(self): return self._b


class FakeSession:
    def __init__(self, total=150, token=True):
        self.headers, self.cookies, self.calls, self.total, self.token = {}, {}, [], total, token

    def post(self, url, json=None, params=None, headers=None, timeout=None):
        if url.endswith("csrf/token"):
            if self.token:
                self.cookies["atsx-csrf-token"] = "abc%3D"
            return FakeResp({"code": 0, "data": {}})
        self.calls.append((json["offset"], headers["x-csrf-token"]))
        ids = range(json["offset"], min(json["offset"] + json["limit"], self.total))
        return FakeResp({"code": 0, "data": {"count": self.total,
                                             "job_post_list": [{"id": i + 1, "title": f"岗位{i}"} for i in ids]}})


def test_feishu_fetch_all_pages_and_token():
    s = FakeSession(total=150)
    jobs, total = c.feishu_fetch_all("h.jobs.feishu.cn", "1", "MiniMax", session=s)
    assert total == 150 and len(jobs) == 150 and len({j["id"] for j in jobs}) == 150
    assert s.calls == [(0, "abc="), (100, "abc=")]                             # дві сторінки, токен розкодовано
    with pytest.raises(ValueError):
        c.feishu_fetch_all("h", "1", "MiniMax", session=FakeSession(token=False))


def test_lab_classes_and_env(monkeypatch):
    assert c.MoonshotJobs.source == "moonshot_careers" and (c.MoonshotJobs.org, c.MoonshotJobs.site) == ("moonshot", "148506")
    assert c.ZhipuJobs.source == "zhipu_careers" and (c.ZhipuJobs.org, c.ZhipuJobs.site) == ("zphz", "148983")
    assert c.MiniMaxJobs.source == "minimax_careers" and c.MiniMaxJobs.tracks_presence
    monkeypatch.setenv("CN_LABS", "zhipu")
    assert c.lab_keys() == ["zhipu"]
    monkeypatch.setenv("CN_LABS", "zhipu,nope")
    with pytest.raises(ValueError):
        c.lab_keys()


def test_incomplete_list_does_not_close_vacancies():
    col = c.MiniMaxJobs.__new__(c.MiniMaxJobs)
    import logging
    col.log = logging.getLogger("t")
    col.load = lambda: ([{"id": "1", "title": "算法工程师", "description": "PyTorch"}], 5, False)
    items = list(col.fetch())
    assert len(items) == 1 and col.tracks_presence is False
    assert col.parse(items[0])["region"] == "China"
    col.load = lambda: ([], 0, True)
    with pytest.raises(ValueError):
        list(col.fetch())


def test_moka_complete():
    assert c.moka_complete(105, 106, "api") and c.moka_complete(132, 137, "api")   # лічильник трохи більший
    assert not c.moka_complete(15, 106, "embedded")                                # запасний режим без API
    assert not c.moka_complete(60, 106, "api")                                     # список обірвався
    assert not c.moka_complete(c.MOKA_MAX, 400, "api") and c.moka_complete(40, None, "api")
