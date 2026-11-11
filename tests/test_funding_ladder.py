from datetime import date

import pandas as pd

from metrics.funding_ladder import (Ttm, asof_dates, build_rows, company_rung, ttm_asof, vendor_stress)


def fin_rows(ticker, quarters, role="lab", filed_lag=30):
    """quarters: [(period_end, {metric: value})]"""
    rows = []
    for end, vals in quarters:
        e = date.fromisoformat(end)
        for m, v in vals.items():
            pt = "instant" if m in ("receivables", "inventory") else "quarter"
            rows.append(dict(ticker=ticker, role=role, metric=m, period_type=pt, period_end=e, value=v,
                             filed_date=e + pd.Timedelta(days=filed_lag).to_pytimedelta()))
    return rows


Q = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


def df(rows):
    return pd.DataFrame(rows)


def test_rungs_by_rule():
    assert company_rung(Ttm({"capex": 50, "ocf": 100}), False) == (0, 0.5)
    assert company_rung(Ttm({"capex": 120, "ocf": 100}), False)[0] == 1
    assert company_rung(Ttm({"capex": 50, "ocf": -10}), False)[0] == 1
    assert company_rung(Ttm({"capex": 50, "ocf": 100, "debt_issued": 6}), False)[0] == 2
    assert company_rung(Ttm({"capex": 50, "ocf": 100, "equity_issued": 3}), False)[0] == 4
    assert company_rung(None, True) == (4, None)
    assert company_rung(None, False) == (None, None)
    assert company_rung(Ttm({"capex": 50}), False) == (None, None)   # без грошового потоку 0 не стверджуємо


def test_ttm_no_lookahead():
    fin = df(fin_rows("X", [(e, {"capex": 10, "ocf": 20}) for e in Q]))
    # останній квартал подано 2026-01-30: на 2026-01-15 відомі лише 3 квартали -> немає TTM з кварталів
    assert ttm_asof(fin, "X", date(2026, 1, 15)) is None
    t = ttm_asof(fin, "X", date(2026, 2, 15))
    assert t.values["capex"] == 40 and t.asof_period == "2025-12-31"


def test_vendor_stress():
    rows = fin_rows("NVDA", [("2024-12-31", {"revenue": 100, "receivables": 50}),
                             ("2025-12-31", {"revenue": 110, "receivables": 80})], role="supplier")
    stress, gap = vendor_stress(df(rows), date(2026, 3, 1))
    assert stress is True and gap == 50.0          # +60 % дебіторки проти +10 % виручки
    assert vendor_stress(df(rows), date(2025, 1, 1)) == (None, None)


def test_build_rows_publishes_max_only_for_labs():
    fin = df(fin_rows("A", [(e, {"capex": 10, "ocf": 20}) for e in Q], filed_lag=45)
             + fin_rows("B", [(e, {"capex": 30, "ocf": 20}) for e in Q], filed_lag=45))
    filings = pd.DataFrame([dict(ticker="C", role="lab", form="S-1", filed_date=date(2026, 1, 20))])
    rows = build_rows(fin, filings, ["A", "B", "C"], date(2026, 2, 28))
    top = {r["period_start"]: r for r in rows if r["metric_id"] == "funding_ladder_rung"}
    assert top["2026-01-31"]["value"] == 4.0                 # IPO компанії C
    assert top["2026-01-31"]["numerator"] == 1               # A і B ще без 4 кварталів
    assert top["2026-02-28"]["value"] == 4.0 and top["2026-02-28"]["numerator"] == 3
    ratio = [r for r in rows if r["metric_id"] == "funding_ladder_capex_ocf" and r["period_start"] == "2026-02-28"]
    assert ratio[0]["value"] == 1.5                          # найвище серед лабораторій
    per_company = {r["region"] for r in rows if r["metric_id"] == "funding_ladder_rung_company"}
    assert per_company == {"A", "B", "C"}


def test_asof_dates_end_today():
    d = asof_dates(date(2026, 11, 11), start=date(2026, 9, 30))
    assert d == [date(2026, 9, 30), date(2026, 10, 31), date(2026, 11, 11)]
