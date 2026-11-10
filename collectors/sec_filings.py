"""Збирач: події з офіційних подань до SEC учасників перегонів.

IPO (S-1, 424B4), повторні розміщення (S-3, 424B5), звіти (10-Q/10-K/20-F),
поточні події 8-K з номерами пунктів (1.05 кіберінцидент, 5.02 зміни керівництва ...),
частки великих власників (13D/13G), дані для голосування (DEF 14A), угоди інсайдерів (Форма 4).

Це стрічка подій для подальшого аналізу реакції ринку (event study).
LLM не використовується: метадані подань структуровані.
"""
from __future__ import annotations

import logging

from core import BaseCollector, RawItem

from collectors._sec_common import (SUBMISSIONS_URL, TICKERS_URL, SecClient, filing_url,
                                    load_companies, recent_filings, resolve_ciks)

log = logging.getLogger(__name__)


class SecFilings(BaseCollector):
    source = "sec_filings"
    fact_table = "fct_lab_filings"
    tracks_presence = False

    def fetch(self):
        sec = SecClient()
        companies = {c.ticker: c for c in load_companies()}
        ciks, skipped = resolve_ciks(sec.get_json(TICKERS_URL), list(companies.values()))
        for msg in skipped:
            log.info("пропущено %s", msg)

        for ticker, cik in ciks.items():
            c = companies[ticker]
            subs = sec.get_json(SUBMISSIONS_URL.format(cik=cik))
            if not subs:
                log.warning("%s: submissions порожні", ticker)
                continue
            for f in recent_filings(subs):
                yield RawItem(external_id=f"{ticker}:{f['accn']}", payload={
                    **f, "ticker": ticker, "cik": cik, "label": c.label, "role": c.role,
                })

    def parse(self, raw):
        p = raw.payload
        return {
            "ticker": p["ticker"],
            "company_label": p["label"],
            "role": p["role"],
            "form": p["form"],
            "category": p["category"],
            "accession_no": p["accn"],
            "filed_date": p["filed"],
            "report_date": p["report_date"],
            "items": p["items"],
            "items_labels": p["items_labels"],
            "description": p["description"],
            "source_url": filing_url(p["cik"], p["accn"]),
            "event_date": p["filed"],
            "extraction_method": "sec_submissions",
        }


if __name__ == "__main__":
    SecFilings().run()
