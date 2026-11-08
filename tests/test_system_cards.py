"""Збирач системних карток: пошук документів, читання PDF, механічна перевірка, автопідтвердження."""

from __future__ import annotations

import io
import json
import subprocess
import textwrap

import pytest

from collectors import system_cards as sc
from collectors._card_verify import check_record, match_second_opinion, normalize
from tests.pgdb import PgDb
from tests.test_framework import ROOT, ARGS, needs_pg, ScriptedLlm

# ---------- тестовий PDF, схожий на картку ----------

PAGE_37 = "2.3.3 Example shortcomings. We sampled 886 day-to-day uses of a nearly-final snapshot."
PAGE_40 = ("2.3.3.3 Works around a block instead of stopping: 9 of 886 transcripts. "
           "The model tried to re-author commits to avoid a two-approval rule.")
PAGE_41 = ("2.3.3.4 Ignores an explicit instruction or required step: 4 of 886 transcripts. "
           "Reports work as done or verified when it was not: 16 of 886.")
PAGE_70 = "7.2 Figure 7 shows severity 3 destructive behavior rates for both models in deployment simulation."


def make_pdf() -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for page in range(1, 71):
        text = {37: PAGE_37, 40: PAGE_40, 41: PAGE_41, 70: PAGE_70}.get(page, f"Page {page} about benchmarks.")
        y = 800
        for line in textwrap.wrap(text, 90):
            c.drawString(40, y, line); y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


ANTHROPIC_INDEX = """<html><body><table>
<tr><td>Claude Mythos 5.1</td><td>September 2026</td><td><a href="https://www-cdn.anthropic.com/abc/Mythos51.pdf">Read system card</a></td></tr>
<tr><td>Claude Opus 4.1</td><td>August 2025</td><td><a href="https://www-cdn.anthropic.com/old/Opus41.pdf">Read system card</a></td></tr>
<tr><td>Usage policy</td><td><a href="https://www.anthropic.com/legal/aup">Read</a></td></tr>
</table></body></html>"""

OPENAI_INDEX = """<html><body><ul>
<li><a href="/gpt-6-astra">GPT-6 Astra System Card</a> Oct 2026</li>
<li><a href="/research-blog">Our research</a></li>
</ul></body></html>"""

GOOD_RECORD = {
    "model_name": "Claude Mythos 5.1", "method": "internal_use_sample", "unit": "use",
    "n_total": 886, "n_total_quote": "We sampled 886 day-to-day uses of a nearly-final snapshot.",
    "n_total_page": "37", "classifier": "Claude-run prompts", "section": "2.3.3",
    "items": [
        {"category": "Works around a block", "is_action": True, "n": 9, "rate_percent": None, "page": "40",
         "quote": "Works around a block instead of stopping: 9 of 886 transcripts."},
        {"category": "Ignores an explicit instruction", "is_action": True, "n": 4, "rate_percent": None, "page": "41",
         "quote": "Ignores an explicit instruction or required step: 4 of 886 transcripts."},
        {"category": "Reports work as done", "is_action": False, "n": 16, "rate_percent": None, "page": "41",
         "quote": "Reports work as done or verified when it was not: 16 of 886."},
    ],
}
FIGURE_RECORD = {
    "model_name": "Claude Mythos 5.1", "method": "deployment_simulation", "unit": "turn",
    "n_total": None, "items": [
        {"category": "Severity 3 destructive", "is_action": True, "n": None, "rate_percent": 0.019, "page": "70",
         "quote": "Figure 7 shows severity 3 destructive behavior rates for both models in deployment simulation."}],
}


@pytest.fixture(scope="module")
def pdf_pages():
    return sc.document_pages(make_pdf(), "application/pdf")


# ---------- чисті функції ----------

def test_discover_indexes():
    a = sc.discover(sc.INDEXES[0], ANTHROPIC_INDEX)
    assert [d["url"] for d in a] == ["https://www-cdn.anthropic.com/abc/Mythos51.pdf",
                                     "https://www-cdn.anthropic.com/old/Opus41.pdf"]
    assert "Mythos 5.1" in a[0]["title"]
    o = sc.discover(sc.INDEXES[1], OPENAI_INDEX)
    assert [d["url"] for d in o] == ["https://deploymentsafety.openai.com/gpt-6-astra"]


def test_pdf_pages_and_relevance(pdf_pages):
    assert len(pdf_pages) == 70 and "886" in pdf_pages["37"]
    rel = sc.relevant_pages(pdf_pages)
    assert {"37", "40", "41", "70"} <= set(rel) and "5" not in rel


def test_real_use_section_not_crowded_out():
    """Великий документ: на 200 сторінках трапляються «destructive»/«unauthorized», але розділ
    про повсякденне використання все одно має потрапити до моделі."""
    pages = {str(i): f"Page {i}: destructive capability evaluation, unauthorized access test. " * 3
             for i in range(1, 251)}
    pages["37"] = PAGE_37
    pages["40"] = PAGE_40
    rel = sc.relevant_pages(pages)
    assert "37" in rel and "40" in rel and "41" in rel     # сусідня сторінка теж (таблиця переходить)


def test_listed_dates_and_order():
    assert sc.listed_date("Oct 30, 2026 GPT-Rosalind-6 System Card") == "2026-10-30"
    assert sc.listed_date("Claude Haiku 4.5 October 2025 Read system card") == "2025-10-01"
    assert sc.listed_date("no date") is None
    html = ('<table><tr><td>Claude Haiku 4.5</td><td>October 2025</td><td><a href="https://www-cdn.anthropic.com/h.pdf">Read system card</a></td></tr>'
            '<tr><td>Claude Mythos 5.1</td><td>September 2026</td><td><a href="https://www-cdn.anthropic.com/m.pdf">Read system card</a></td></tr></table>')
    assert [d["url"][-5:] for d in sc.discover(sc.INDEXES[0], html)] == ["m.pdf", "h.pdf"]


def test_script_text_is_not_a_title():
    html = ('<li><script>class X extends HTMLElement{attributeChangedCallback(){this.hydrate()}}</script>'
            'Nov 05, 2026 <a href="/gpt-6-cyber">GPT-6 Cyber System Card</a></li>')
    d = sc.discover(sc.INDEXES[1], html)[0]
    assert "hydrate" not in d["title"] and d["title"].startswith("Nov 05, 2026")


def test_titles_are_short_model_names():
    a = sc.discover(sc.INDEXES[0], "<html><body><h1>Model system cards</h1><p>System cards document the "
                    "capabilities, safety evaluations and more.</p>" + ANTHROPIC_INDEX[12:])
    assert a[0]["title"].startswith("Claude Mythos 5.1") and "System cards document" not in a[0]["title"]


def test_good_record_passes(pdf_pages):
    ok, log, rate, n_out = check_record(GOOD_RECORD, pdf_pages)
    assert ok, log
    assert n_out == 13 and abs(rate - 13 / 886) < 1e-12        # частку рахує код, неправдиві звіти не входять


def test_figure_only_numbers_fail(pdf_pages):
    ok, log, rate, _ = check_record(FIGURE_RECORD, pdf_pages)
    assert not ok and any("графіку" in l for l in log)


def test_paraphrased_quote_or_wrong_number_fails(pdf_pages):
    bad = json.loads(json.dumps(GOOD_RECORD))
    bad["items"][0]["quote"] = "The model worked around blocks in 9 of 886 cases."
    assert not check_record(bad, pdf_pages)[0]
    bad = json.loads(json.dumps(GOOD_RECORD))
    bad["items"][0]["n"] = 19
    ok, log, *_ = check_record(bad, pdf_pages)
    assert not ok and any("19" in l for l in log)


def test_second_opinion():
    same = json.loads(json.dumps(GOOD_RECORD)); same["model_name"] = "claude mythos 5.1"
    assert match_second_opinion(GOOD_RECORD, [same])[0]
    diff = json.loads(json.dumps(GOOD_RECORD)); diff["items"][2]["is_action"] = True
    assert not match_second_opinion(GOOD_RECORD, [diff])[0]   # інша класифікація дій - не згода
    assert not match_second_opinion(GOOD_RECORD, [])[0]


def test_normalize():
    assert normalize("“Works around” a ﬁle-\nsystem") == '"works around" a filesystem'


# ---------- збирач цілком ----------

@pytest.fixture()
def db():
    base = ARGS + ["-v", "ON_ERROR_STOP=1", "-q"]
    subprocess.run(["psql", *base, "-c", "DROP DATABASE IF EXISTS radar_sc", "-c", "CREATE DATABASE radar_sc"],
                   check=True, capture_output=True)
    dbargs = ARGS + ["-d", "radar_sc"]
    for f in ["tests/sql/legacy_schema.sql", "tests/sql/horizons_schema.sql", "sql/001_core_framework.sql",
              "sql/004_autonomy_horizons.sql", "sql/005_leader_actions.sql", "sql/006_system_cards_auto.sql",
              "sql/007_leader_by_eci.sql", "sql/008_cards_reprocess.sql", "sql/009_cards_queue_and_keys.sql",
              "sql/009_cards_queue_and_keys.sql"]:
        subprocess.run(["psql", *dbargs, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / f)],
                       check=True, capture_output=True)
    return PgDb(dbargs)


class Resp:
    def __init__(self, content: bytes, ctype: str):
        self.content, self.headers = content, {"content-type": ctype}
        self.text = content.decode("utf-8", errors="replace")


@needs_pg
def test_collector_end_to_end(db, monkeypatch):
    pdf = make_pdf()
    calls = []

    def fake_get(url):
        calls.append(url)
        if url == sc.INDEXES[0]["url"]:
            return Resp(ANTHROPIC_INDEX.encode(), "text/html")
        if url == sc.INDEXES[1]["url"]:
            return Resp(b"<html></html>", "text/html")             # порожній покажчик -> попередження
        return Resp(pdf, "application/pdf")

    monkeypatch.setattr(sc, "http_get", fake_get)
    monkeypatch.setenv("CARDS_MAX_PER_RUN", "1")
    extraction = {"document_date": "2026-09-01", "records": [GOOD_RECORD, FIGURE_RECORD]}
    # людина раніше вручну підтвердила старий запис - збирач його не чіпає
    db.insert("fct_leader_action_rates", {
        "lab": "Anthropic", "model_name": "Claude Mythos 5", "release_date": "2026-06-09", "source_doc": "m5",
        "source_url": "https://example/m5.pdf", "method": "internal_use_sample", "unit": "use",
        "n_total": 886, "n_out": 13, "rate_out": 13 / 886, "verified": True, "verified_by": "human"})

    stats = sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": extraction, "m2": extraction})).run()
    assert stats["failed"] == 0 and stats["seen"] == 1
    assert not any("Opus41" in u for u in calls)                             # стара картка не завантажувалась
    old = db.select("ops_documents", eq={"url": "https://www-cdn.anthropic.com/old/Opus41.pdf"})[0]
    assert old["status"] == "no_real_use_data" and "2025-08-01" in old["note"]
    rows = {(r["model_name"], r["method"]): r for r in db.select("fct_leader_action_rates")}
    good = rows[("Claude Mythos 5.1", "internal_use_sample")]
    assert good["verified"] is True and good["verified_by"] == "auto"
    assert good["n_out"] == 13 and abs(float(good["rate_out"]) - 13 / 886) < 1e-9
    assert [c["category"] for c in good["counted"]] == ["Works around a block", "Ignores an explicit instruction"]
    fig = rows[("Claude Mythos 5.1", "deployment_simulation")]
    assert fig["verified"] is False and fig["verified_by"] is None          # числа лише на графіку
    assert rows[("Claude Mythos 5", "internal_use_sample")]["verified_by"] == "human"

    # на колі: Anthropic тепер Mythos 5.1 (новіша), OpenAI - старий запис ще не підтверджено
    models = db.select("v_leader_action_models")
    assert [(m["lab"], m["model_name"]) for m in models] == [("Anthropic", "Claude Mythos 5.1")]
    assert db.select("ops_quality_alerts", eq={"check_name": "index_empty"})
    assert db.select("ops_quality_alerts", eq={"check_name": "pending_human_review"})

    # наступного дня той самий документ не завантажується вдруге
    calls.clear()
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": extraction, "m2": extraction})).run()
    assert not any(u.endswith(".pdf") and "Mythos51" in u for u in calls)
    doc = db.select("ops_documents", eq={"url": "https://www-cdn.anthropic.com/abc/Mythos51.pdf"})[0]
    assert "37" in doc["note"] and doc["processed_version"] == sc.PROCESSING_VERSION

    # змінилась версія обробки - документ переглядається знову
    db.update("ops_documents", {"processed_version": "старa"}, eq={"url": doc["url"]})
    calls.clear()
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": extraction, "m2": extraction})).run()
    assert any("Mythos51" in u for u in calls)


@needs_pg
def test_collector_without_second_opinion_does_not_autoverify(db, monkeypatch):
    pdf = make_pdf()
    monkeypatch.setattr(sc, "http_get", lambda url: Resp(ANTHROPIC_INDEX.encode(), "text/html")
                        if url == sc.INDEXES[0]["url"] else Resp(b"", "text/html") if url == sc.INDEXES[1]["url"]
                        else Resp(pdf, "application/pdf"))
    monkeypatch.setenv("CARDS_MAX_PER_RUN", "1")
    extraction = {"document_date": "2026-09-01", "records": [GOOD_RECORD]}
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": extraction})).run()        # m2/m3 вичерпали квоту
    r = db.select("fct_leader_action_rates", eq={"model_name": "Claude Mythos 5.1"})[0]
    assert r["verified"] is False and any("друга модель" in l for l in r["verification_log"])


@needs_pg
def test_links_inside_cards_are_queued(db, monkeypatch):
    """Основна картка GPT-6 є лише в посиланнях із доповнення - збирач її знаходить і обробляє наступного дня."""
    addendum = (b'<html><body><h1>Addendum to GPT-6 Astra System Card: GPT-6.1 Sol</h1>'
                b'<p>See the <a href="/gpt-6-astra">GPT-6 Astra System Card</a>.</p><p>Nothing else.</p></body></html>')
    main_card = b'<html><body><h1>GPT-6 Astra System Card</h1><p>capabilities</p></body></html>'
    calls = []

    def fake_get(url):
        calls.append(url)
        if url == sc.INDEXES[0]["url"]:
            return Resp(b"<html></html>", "text/html")
        if url == sc.INDEXES[1]["url"]:
            return Resp(b'<li>Sep 29, 2026 <a href="/gpt-6-1-sol">Addendum to GPT-6 Astra System Card: GPT-6.1 Sol</a></li>',
                        "text/html")
        if url.endswith("/gpt-6-1-sol"):
            return Resp(addendum, "text/html")
        return Resp(main_card, "text/html")

    monkeypatch.setattr(sc, "http_get", fake_get)
    empty = {"document_date": "2026-09-29", "records": []}
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": empty})).run()
    q = db.select("ops_documents", eq={"url": "https://deploymentsafety.openai.com/gpt-6-astra"})
    assert q and q[0]["status"] == "queued"

    calls.clear()
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": empty})).run()
    assert "https://deploymentsafety.openai.com/gpt-6-astra" in calls
    assert db.select("ops_documents", eq={"url": "https://deploymentsafety.openai.com/gpt-6-astra"})[0]["status"] != "queued"


@needs_pg
def test_same_model_spelled_differently_is_one_row(db, monkeypatch):
    pdf = make_pdf()
    monkeypatch.setattr(sc, "http_get", lambda url: Resp(ANTHROPIC_INDEX.encode(), "text/html")
                        if url == sc.INDEXES[0]["url"] else Resp(b"", "text/html") if url == sc.INDEXES[1]["url"]
                        else Resp(pdf, "application/pdf"))
    monkeypatch.setenv("CARDS_MAX_PER_RUN", "1")
    dash = json.loads(json.dumps(GOOD_RECORD)); dash["model_name"] = "Claude-Mythos-5.1"
    extraction = {"document_date": "2026-09-01", "records": [GOOD_RECORD, dash]}
    sc.SystemCards(db=db, llm=ScriptedLlm(db, {"m1": extraction, "m2": extraction})).run()
    rows = db.select("fct_leader_action_rates", eq={"lab": "Anthropic"})
    assert len([r for r in rows if r["model_key"] == "claude mythos 5 1"]) == 1
