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


# ---------------- зашифрований список через API ----------------

import base64

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY, IV = "cfe18ac03acf564f", "de7c21ed8d6f50fe"


def encrypt(obj) -> dict:
    p = padding.PKCS7(128).padder()
    raw = p.update(json.dumps(obj, ensure_ascii=False).encode()) + p.finalize()
    e = Cipher(algorithms.AES(KEY.encode()), modes.CBC(IV.encode())).encryptor()
    return {"data": base64.b64encode(e.update(raw) + e.finalize()).decode(), "necromancer": KEY}


def test_decrypt_roundtrip_and_errors():
    body = encrypt({"code": 0, "data": {"jobs": [{"id": "x"}]}})
    assert ds.open_response(body, IV) == {"jobs": [{"id": "x"}]}
    with pytest.raises(ValueError):
        ds.open_response({"code": 102, "msg": "参数错误", "success": False}, IV)


API_JOBS = [{"id": f"j{i}", "title": f"岗位{i}", "status": "open", "openedAt": "2026-06-24T00:00",
             "jobDescription": "<p>负责 Agent 训练</p>", "zhineng": {"id": 1, "name": "深度学习"},
             "locations": [{"provinceName": "北京市", "cityName": "海淀区", "address": "融科资讯中心"}]}
            for i in range(20)]


class FakeResp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, fail=False):
        self.headers, self.calls, self.fail = {}, [], fail

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        if self.fail:
            return FakeResp({"code": 500, "success": False})
        chunk = API_JOBS[json["offset"]: json["offset"] + json["limit"]]
        return FakeResp(encrypt({"code": 0, "data": {"jobStats": {"total": 0}, "jobs": chunk}}))


def embedded_page(total=20):
    state = {"jobs": JOBS[:1], "jobStats": {"total": total}, "aesIv": IV}
    return f'<div data-x="{html.escape(json.dumps(state, ensure_ascii=False))}"></div>'


def test_fetch_all_pages_with_descriptions(monkeypatch):
    monkeypatch.setattr(ds, "get_with_retry", lambda *a, **k: type("R", (), {"text": embedded_page()})())
    s = FakeSession()
    jobs, total, mode = ds.fetch_all(session=s, sleep=lambda x: None)
    assert mode == "api" and total == 20 and len(jobs) == 20 and len(s.calls) == 2
    j = jobs[0]
    assert j["description"] == "负责 Agent 训练" and j["location"] == "北京市海淀区" and j["category"] == "深度学习"


def test_fetch_all_falls_back_to_embedded(monkeypatch):
    monkeypatch.setattr(ds, "get_with_retry", lambda *a, **k: type("R", (), {"text": embedded_page()})())
    jobs, total, mode = ds.fetch_all(session=FakeSession(fail=True), sleep=lambda x: None)
    assert mode == "embedded" and len(jobs) == 1
