"""core/http.py: повтори при тимчасових збоях і вирізання ключів з помилок."""

from __future__ import annotations

import pytest
import requests

from core import http


class Resp:
    def __init__(self, code, url="https://api.adzuna.com/x?app_id=ID1&app_key=KEY123"):
        self.status_code, self.url = code, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error for url: {self.url}", response=self)


def run(monkeypatch, codes):
    seq, sleeps = list(codes), []
    monkeypatch.setattr(http.requests, "get", lambda url, **kw: Resp(seq.pop(0)))
    try:
        return http.get_with_retry("u", sleep=sleeps.append), sleeps
    except Exception as e:
        return e, sleeps


def test_retries_then_succeeds(monkeypatch):
    r, sleeps = run(monkeypatch, [503, 503, 200])
    assert r.status_code == 200 and sleeps == [5, 15]


def test_gives_up_with_redacted_error(monkeypatch):
    e, sleeps = run(monkeypatch, [503, 503, 503])
    assert isinstance(e, requests.HTTPError) and sleeps == [5, 15]
    assert "KEY123" not in str(e) and "ID1" not in str(e) and "app_key=***" in str(e)


def test_no_retry_on_client_error(monkeypatch):
    e, sleeps = run(monkeypatch, [401])
    assert isinstance(e, requests.HTTPError) and sleeps == []


def test_retries_connection_error(monkeypatch):
    calls = []

    def boom(url, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectionError("reset")
        return Resp(200)
    monkeypatch.setattr(http.requests, "get", boom)
    assert http.get_with_retry("u", sleep=lambda s: None).status_code == 200


def test_redact(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-secret-999")
    txt = "url ?app_id=a1&app_key=b2&what=x token=zz; boom gem-secret-999"
    out = http.redact(txt)
    assert "a1" not in out and "b2" not in out and "zz" not in out and "gem-secret-999" not in out
    assert "what=x" in out
    assert http.redact(None) is None
