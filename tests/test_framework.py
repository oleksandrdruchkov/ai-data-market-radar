"""
Наскрізні тести каркаса на локальному Postgres (схема = legacy + sql/001).
Запуск:  RADAR_TEST_PG="-h /tmp -p 5499 -U postgres" python -m pytest -q tests
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.llm import Llm
from core import quality
from collectors.jobs_deepseek import DeepSeekJobs
from collectors.arxiv import ArxivSignals, parse_feed
from collectors import jobs_adzuna
from tests.pgdb import PgDb, pg_args

ROOT = Path(__file__).resolve().parents[1]
ARGS = pg_args()
needs_pg = pytest.mark.skipif(ARGS is None, reason="RADAR_TEST_PG не задано")

GOOD = {"title_en": "CUDA Kernel Engineer", "experience_level": "Senior", "work_model": "On-site",
        "track": "Machine Learning",
        "skills": [{"name": "CUDA", "category": "AI Hardware/Kernel"},
                   {"name": "PyTorch", "category": "Deep Learning Framework"},
                   {"name": "Triton", "category": "SomethingNew"}]}


class ScriptedLlm(Llm):
    """Gemini-замінник: behaviour[model] = 'ok' | 'quota' | 'bad' | dict."""

    def __init__(self, db, behaviour: dict, **kw):
        super().__init__(db=db, models=["m1", "m2", "m3"], min_interval_sec=0, **kw)
        self.behaviour = behaviour
        self.prompts: list[str] = []

    def _get_client(self):
        return object()

    def _call(self, model, prompt, temperature):
        self.prompts.append(model)
        b = self.behaviour.get(model, "quota")
        if b == "quota":
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        if b == "bad":
            return json.dumps({**GOOD, "track": "Astrology"})
        return json.dumps(b if isinstance(b, dict) else GOOD)


@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_test",
                    "-c", "CREATE DATABASE radar_test"], check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_test"]
    for f in ["tests/sql/legacy_schema.sql", "sql/001_core_framework.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    return PgDb(dbargs)


@pytest.fixture(autouse=True)
def no_exit(monkeypatch):
    monkeypatch.setenv("RADAR_FAIL_ON_CRITICAL", "0")


def seed(tmp_path, monkeypatch, ids):
    src = json.loads((ROOT / "collectors/seeds/deepseek_manual.json").read_text())
    path = tmp_path / "seed.json"
    path.write_text(json.dumps([j for j in src if j["id"] in ids], ensure_ascii=False))
    monkeypatch.setenv("DEEPSEEK_SEED_FILE", str(path))


ALL = ["ds-kernel-01", "ds-rl-02", "ds-infra-03"]


@needs_pg
def test_happy_path_and_cache(db, tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, ALL)
    stats = DeepSeekJobs(db=db, llm=ScriptedLlm(db, {"m1": "ok"})).run()
    assert stats["seen"] == 3 and stats["failed"] == 0 and stats["deferred"] == 0
    # ds-kernel-01 уже був у legacy-даних з тим самим external_id -> оновлено, не задубльовано
    rows = db.select("fct_vacancies", eq={"source": "deepseek_careers"}, order="external_id")
    assert len(rows) == 3
    assert {r["extraction_method"] for r in rows} == {"llm:m1"}
    assert all(r["collection_method"] == "manual_seed" and r["source_url"] is None for r in rows)
    assert all(r["verified"] is False and r["is_active"] for r in rows)
    legacy = [r for r in rows if r["external_id"] == "ds-kernel-01"][0]
    assert legacy["title_original"].startswith("大模型") and legacy["title"] == "CUDA Kernel Engineer"
    assert legacy["first_seen_at"].startswith("2026-10-20")       # first_seen = created_at, не перезаписано
    skills = db.select("bridge_vacancy_skills", eq={"vacancy_id": legacy["id"]})
    assert len(skills) == 3
    triton = db.select("dim_skills", eq={"canonical_name": "Triton"})[0]
    assert triton["category"] == "Tool"                           # невідома категорія -> Tool
    run = db.select("ops_collector_runs", order="run_id", desc=True, limit=1)[0]
    assert run["status"] == "ok" and run["items_seen"] == 3 and run["llm_calls"] == 3

    # Другий запуск: той самий текст -> кеш, жодного виклику моделі
    llm2 = ScriptedLlm(db, {"m1": "ok"})
    stats2 = DeepSeekJobs(db=db, llm=llm2).run()
    assert llm2.prompts == [] and stats2["llm_cache_hits"] == 3 and stats2["updated"] == 3
    assert len(db.select("raw_items", eq={"source": "deepseek_careers"})) == 3 + 1  # +1 legacy


@needs_pg
def test_cascade_fallback_and_schema_validation(db, tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, ["ds-rl-02"])
    llm = ScriptedLlm(db, {"m1": "quota", "m2": "bad", "m3": "ok"})
    stats = DeepSeekJobs(db=db, llm=llm).run()
    assert llm.prompts == ["m1", "m2", "m3"]
    assert stats["llm_fallbacks"] == 1
    row = db.select("fct_vacancies", eq={"external_id": "ds-rl-02"})[0]
    assert row["extraction_method"] == "llm:m3" and row["track"] == "Machine Learning"


@needs_pg
def test_llm_down_defers_then_backlog_processed_and_stale_closed(db, tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, ALL)
    stats = DeepSeekJobs(db=db, llm=ScriptedLlm(db, {})).run()      # усі моделі 429
    assert stats["deferred"] == 3
    assert len(db.select("fct_vacancies", eq={"source": "deepseek_careers"})) == 1   # лише legacy
    assert len(db.select("raw_items", eq={"source": "deepseek_careers", "status": "deferred"})) == 3
    assert db.select("ops_collector_runs", order="run_id", desc=True, limit=1)[0]["status"] == "partial"
    alerts = db.select("ops_quality_alerts", eq={"check_name": "deferred_share"})
    assert alerts and alerts[0]["severity"] == "warning"

    # Наступного дня у списку лишилась одна вакансія, LLM знову працює
    seed(tmp_path, monkeypatch, ["ds-rl-02"])
    stats = DeepSeekJobs(db=db, llm=ScriptedLlm(db, {"m1": "ok"})).run()
    assert stats["seen"] == 1 and stats["reprocessed"] == 2
    rows = {r["external_id"]: r for r in db.select("fct_vacancies", eq={"source": "deepseek_careers"})}
    assert rows["ds-rl-02"]["is_active"] is True
    # дві вакансії, які зникли зі списку, оброблено з відкладених і закрито як зниклі
    assert rows["ds-kernel-01"]["is_active"] is False and rows["ds-infra-03"]["is_active"] is False
    assert db.select("raw_items", eq={"source": "deepseek_careers", "status": "deferred"}) == []


@needs_pg
def test_fetch_failure_does_not_close_anything(db, tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch, ALL)
    DeepSeekJobs(db=db, llm=ScriptedLlm(db, {"m1": "ok"})).run()
    monkeypatch.setenv("DEEPSEEK_SEED_FILE", str(tmp_path / "missing.json"))
    stats = DeepSeekJobs(db=db, llm=ScriptedLlm(db, {"m1": "ok"})).run()
    assert stats["closed"] == 0
    assert all(r["is_active"] for r in db.select("fct_vacancies", eq={"source": "deepseek_careers"}))
    assert db.select("ops_quality_alerts", eq={"check_name": "fetch_failed", "severity": "critical"})
    fresh = {r["source"]: r for r in db.select("v_ops_source_freshness")}
    assert fresh["deepseek_careers"]["freshness"] == "failing"


@needs_pg
def test_adzuna(db, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "x")
    monkeypatch.setenv("ADZUNA_APP_KEY", "y")
    monkeypatch.setenv("ADZUNA_MARKETS", "us:US:USD")

    class Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"results": [
                {"id": "111", "title": "Data Engineer", "description": "Python, Spark, Airflow",
                 "company": {"display_name": "Acme"}, "location": {"display_name": "NYC"},
                 "created": "2026-11-06T10:00:00Z", "salary_min": 120000, "salary_is_predicted": "1",
                 "redirect_url": "https://www.adzuna.com/details/111"}]}

    from core import http
    monkeypatch.setattr(http.requests, "get", lambda *a, **k: Resp())     # запити йдуть через core.http
    good = {**GOOD, "track": "Data Engineering", "experience_level": "Not Specified",
            "skills": [{"name": "Python", "category": "Language"}]}
    stats = jobs_adzuna.AdzunaJobs(db=db, llm=ScriptedLlm(db, {"m1": good})).run()
    assert stats["seen"] == 1 and stats["updated"] + stats["new"] == 1
    # legacy-рядок adzuna_us/111 після міграції має id us:111 -> оновлено, не задубльовано
    rows = db.select("fct_vacancies", eq={"source": "adzuna", "external_id": "us:111"})
    assert len(rows) == 1
    r = rows[0]
    assert r["event_date"] == "2026-11-06" and r["salary_is_predicted"] is True
    assert r["source_url"].endswith("/111") and r["first_seen_at"].startswith("2026-10-01") and r["event_date"] == "2026-11-06"


SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry><id>http://arxiv.org/abs/2611.00003v1</id><published>2026-11-05T17:00:00Z</published>
  <title>Agent   Memory
  at Scale</title><summary>We study long-horizon agents.</summary>
  <arxiv:primary_category term="cs.LG"/><category term="cs.AI"/></entry>
 <entry><title>No id</title></entry>
</feed>"""


def test_parse_feed():
    papers = parse_feed(SAMPLE_FEED)
    assert len(papers) == 1
    p = papers[0]
    assert p["arxiv_id"] == "2611.00003v1" and p["title"] == "Agent Memory at Scale"
    assert p["category"] == "cs.LG" and p["published"] == "2026-11-05"


@needs_pg
def test_arxiv(db, monkeypatch):
    import collectors.arxiv as ax

    class Resp:
        status_code, content, headers = 200, SAMPLE_FEED, {}
        def raise_for_status(self): pass

    monkeypatch.setattr(ax.requests, "get", lambda *a, **k: Resp())
    sig = {"predicted_skill": "Agent Memory", "predicted_role_en": "Agent Engineer",
           "predicted_role_ua": "Інженер агентів", "signal_summary_en": "Long-horizon agents need memory.",
           "signal_summary_ua": "Довгим агентам потрібна пам'ять."}
    ArxivSignals(db=db, llm=ScriptedLlm(db, {"m1": sig})).run()
    r = db.select("fct_arxiv_signals", eq={"arxiv_id": "2611.00003v1"})[0]
    assert r["source"] == "arxiv" and r["event_date"] == "2026-11-05"
    assert json.loads(r["signal_summary"])["ua"].startswith("Довгим")
    assert r["source_url"] == "http://arxiv.org/abs/2611.00003v1"


FALLBACK_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry><id>http://arxiv.org/abs/2611.00002v1</id><published>2026-11-02T10:00:00Z</published>
  <title>Paper B</title><summary>A real abstract about test-time compute scaling.</summary>
  <arxiv:primary_category term="cs.LG"/></entry>
 <entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_bad</id><title>Error</title>
  <summary>incorrect id format</summary></entry>
</feed>"""


@needs_pg
def test_arxiv_reanalyze(db, monkeypatch):
    import collectors.arxiv as ax
    from collectors.arxiv_reanalyze import ArxivReanalyze
    calls = []

    class Resp:
        status_code, content, headers = 200, FALLBACK_FEED, {}
        def raise_for_status(self): pass

    def fake_get(url, params=None, **k):
        calls.append(params)
        return Resp()

    monkeypatch.setattr(ax.requests, "get", fake_get)
    sig = {"predicted_skill": "Test-Time Compute", "predicted_role_en": "Inference Engineer",
           "predicted_role_ua": "Інженер інференсу", "signal_summary_en": "Compute moves to inference time.",
           "signal_summary_ua": "Обчислення переходять у час інференсу."}
    stats = ArxivReanalyze(db=db, llm=ScriptedLlm(db, {"m1": sig})).run()
    assert calls[0]["id_list"] == "2611.00002v1"
    assert stats["seen"] == 1 and stats["failed"] == 0
    r = db.select("fct_arxiv_signals", eq={"arxiv_id": "2611.00002v1"})[0]
    assert r["extraction_method"] == "llm:m1" and r["predicted_skill"] == "Test-Time Compute"
    assert r["first_seen_at"].startswith("2026-11-03")             # перша поява не змінилась
    assert len(db.select("fct_arxiv_signals")) == 2                 # службовий «Error» не записано
    assert db.select("ops_collector_runs", order="run_id", desc=True, limit=1)[0]["source"] == "arxiv_reanalyze"

    # Повторний запуск: переаналізувати нічого, але це не помилка
    stats = ArxivReanalyze(db=db, llm=ScriptedLlm(db, {"m1": sig})).run()
    assert stats["seen"] == 0 and len(calls) == 1
    assert not db.select("ops_quality_alerts", eq={"source": "arxiv_reanalyze", "severity": "critical"})


def test_quality_rules():
    ev = quality.evaluate
    assert ev({"seen": 0}, "ok", None, [])[0]["check_name"] == "empty_fetch"
    assert ev({"seen": 10}, "failed", "boom", [])[0]["severity"] == "critical"
    a = ev({"seen": 4}, "ok", None, [10, 10, 12, 9])
    assert [x["check_name"] for x in a] == ["volume_change"]
    assert ev({"seen": 10}, "ok", None, [10, 11, 9]) == []
    assert ev({"seen": 10, "failed": 6}, "partial", None, [])[0]["severity"] == "critical"
