"""Збирач: квартальні фінансові показники учасників перегонів з офіційних XBRL-даних SEC.

Що збирає (на кожну компанію з seeds/market_companies.json):
  revenue, capex (купівля обладнання й дата-центрів = паливо обчислень),
  rnd, net_income, cash.
LLM не використовується: дані вже структуровані й подані під відповідальність емітента.
"""
from __future__ import annotations

import logging

from core import BaseCollector, RawItem

from collectors._sec_common import (FACTS_URL, TICKERS_URL, SecClient, extract_metrics,
                                    filing_url, load_companies, resolve_ciks)

log = logging.getLogger(__name__)


class SecFinancials(BaseCollector):
    source = "sec_financials"
    fact_table = "fct_lab_financials"
    tracks_presence = False          # SEC не видаляє дані; закривати факти нема підстав

    def fetch(self):
        sec = SecClient()
        companies = {c.ticker: c for c in load_companies()}
        ciks, skipped = resolve_ciks(sec.get_json(TICKERS_URL), list(companies.values()))
        for msg in skipped:
            log.info("пропущено %s", msg)

        for ticker, cik in ciks.items():
            c = companies[ticker]
            facts = sec.get_json(FACTS_URL.format(cik=cik))
            if not facts:
                log.warning("%s: companyfacts порожні", ticker)
                continue
            for row in extract_metrics(facts):
                ext_id = f"{ticker}:{row['metric']}:{row['period_type']}:{row['period_end']}"
                yield RawItem(external_id=ext_id, payload={
                    **row, "ticker": ticker, "cik": cik, "label": c.label, "role": c.role,
                })

    def parse(self, raw):
        p = raw.payload
        return {
            "ticker": p["ticker"],
            "company_label": p["label"],
            "role": p["role"],
            "metric": p["metric"],
            "period_type": p["period_type"],
            "period_start": p["period_start"],
            "period_end": p["period_end"],
            "value": p["value"],
            "currency": p["currency"],
            "derived_from_ytd": p["derived"],
            "xbrl_concept": p["xbrl_concept"],
            "form": p["form"],
            "accession_no": p["accn"],
            "filed_date": p["filed"],
            "source_url": filing_url(p["cik"], p["accn"]),
            "event_date": p["filed"],
            "extraction_method": "sec_xbrl",
        }


if __name__ == "__main__":
    SecFinancials().run()
