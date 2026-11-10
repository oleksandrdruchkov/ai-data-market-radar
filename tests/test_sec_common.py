import json
from pathlib import Path

import pytest

from collectors._sec_common import (Company, extract_metrics, load_companies, quarterly_series,
                                    recent_filings, resolve_ciks)


def f(start, end, val, filed, form="10-Q", accn="0000000000-26-000001"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": accn}


def quarters(rows):
    return {r["period_end"]: r for r in rows if r["period_type"] == "quarter"}


def test_ytd_cashflow_becomes_quarters():
    # Капвитрати в 10-Q подаються накопичувально: 3, 6, 9 міс., у 10-K - рік
    entries = [
        f("2025-01-01", "2025-03-31", 10, "2025-04-25"),
        f("2025-01-01", "2025-06-30", 25, "2025-07-25"),
        f("2025-01-01", "2025-09-30", 45, "2025-10-25"),
        f("2025-01-01", "2025-12-31", 70, "2026-02-01", form="10-K"),
    ]
    q = quarters(quarterly_series(entries))
    assert [q[d]["value"] for d in sorted(q)] == [10, 15, 20, 25]
    assert q["2025-03-31"]["derived"] is False
    assert q["2025-06-30"]["derived"] is True
    assert q["2025-06-30"]["period_start"] == "2025-04-01"
    years = [r for r in quarterly_series(entries) if r["period_type"] == "year"]
    assert years[0]["value"] == 70


def test_direct_quarter_wins_and_latest_filing_wins():
    entries = [
        f("2025-04-01", "2025-06-30", 100, "2025-07-25"),
        f("2025-04-01", "2025-06-30", 105, "2026-07-25"),   # перераховано в наступному році
        f("2025-01-01", "2025-06-30", 999, "2025-07-25"),   # накопичувальне - не має перебити пряме
        f("2025-01-01", "2025-03-31", 1, "2025-04-25"),
    ]
    q = quarters(quarterly_series(entries))
    assert q["2025-06-30"]["value"] == 105
    assert q["2025-06-30"]["derived"] is False


def test_noncalendar_fiscal_year():
    # Microsoft: фінансовий рік з 1 липня
    entries = [
        f("2025-07-01", "2025-09-30", 20, "2025-10-30"),
        f("2025-07-01", "2025-12-31", 50, "2026-01-30"),
    ]
    q = quarters(quarterly_series(entries))
    assert q["2025-12-31"]["value"] == 30


def test_ignores_non_periodic_forms_and_old_data():
    entries = [
        f("2025-01-01", "2025-03-31", 10, "2025-04-25", form="8-K"),
        f("2015-01-01", "2015-03-31", 10, "2015-04-25"),
    ]
    assert quarterly_series(entries) == []


def test_instant_metric():
    entries = [{"end": "2025-06-30", "val": 7, "filed": "2025-07-25", "form": "10-Q", "accn": "a"}]
    rows = quarterly_series(entries, instant=True)
    assert rows[0]["period_type"] == "instant" and rows[0]["value"] == 7


def test_extract_metrics_concept_fallback_and_currency():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [f("2025-01-01", "2025-03-31", 5, "2025-04-25")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            f("2025-01-01", "2025-03-31", 999, "2025-04-25"),   # той самий період - не перебиває
            f("2025-04-01", "2025-06-30", 6, "2025-07-25"),     # заповнює прогалину
        ]}},
        "NetIncomeLoss": {"units": {"CNY": [f("2025-04-01", "2025-06-30", -3, "2025-07-25")]}},
    }}}
    rows = extract_metrics(facts)
    rev = {r["period_end"]: r for r in rows if r["metric"] == "revenue"}
    assert rev["2025-03-31"]["value"] == 5 and rev["2025-03-31"]["xbrl_concept"] == "Revenues"
    assert rev["2025-06-30"]["value"] == 6
    ni = [r for r in rows if r["metric"] == "net_income"][0]
    assert ni["currency"] == "CNY" and ni["value"] == -3


def test_resolve_ciks_checks_name():
    tickers = {
        "0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "1": {"cik_str": 1, "ticker": "ANT", "title": "Some Ant Farm Corp"},
    }
    cs = [Company("GOOGL", "ALPHABET", "Alphabet", "lab"),
          Company("ANT", "ANTHROPIC", "Anthropic", "lab"),
          Company("XYZ", "XYZ", "XYZ", "lab")]
    found, skipped = resolve_ciks(tickers, cs)
    assert found == {"GOOGL": 1652044}
    assert len(skipped) == 2 and any("Some Ant Farm" in s for s in skipped)


def test_recent_filings_filter_and_8k_items():
    subs = {"filings": {"recent": {
        "accessionNumber": ["a1", "a2", "a3", "a4"],
        "form": ["8-K", "S-1", "SD", "8-K"],
        "filingDate": ["2026-10-01", "2026-10-26", "2026-10-02", "2018-01-01"],
        "reportDate": ["2026-09-30", "", "", ""],
        "primaryDocument": ["x.htm", "s1.htm", "sd.htm", "o.htm"],
        "primaryDocDescription": ["8-K", "S-1", "SD", "8-K"],
        "items": ["1.05,9.01", "", "", "2.02"],
    }}}
    out = recent_filings(subs)
    assert [r["accn"] for r in out] == ["a1", "a2"]
    assert out[0]["items"] == ["1.05", "9.01"]
    assert out[0]["items_labels"] == ["суттєвий кіберінцидент"]
    assert out[1]["category"] == "ipo"


def test_seed_file_is_valid():
    cs = load_companies()
    assert {c.role for c in cs} <= {"lab", "backer", "supplier"}
    assert len({c.ticker for c in cs}) == len(cs)
