"""
collectors/arxiv.py
Свіжі препринти ArXiv (cs.AI, cs.CL, cs.LG) -> сигнали майбутніх навичок і ролей.
Замінює collector_arxiv.py. Формат signal_summary (JSON-рядок en/ua/role_en/role_ua)
збережено, щоб app.py працював без змін.

Змінні: ARXIV_MAX_RESULTS=5
Запуск: python -m collectors.arxiv
"""

from __future__ import annotations

import os
import json
import time
import xml.etree.ElementTree as ET

import requests
from pydantic import BaseModel, Field

from core import BaseCollector, RawItem

API_URL = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
HEADERS = {
    "User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)",
    "Accept": "application/atom+xml,application/xml,text/xml",
}
MAX_RETRIES, BACKOFF_BASE, MAX_WAIT = 4, 30, 300
PROMPT_VERSION = "arxiv_signal_v2"


class ArxivSignal(BaseModel):
    predicted_skill: str = Field(min_length=2, max_length=80)
    predicted_role_en: str = Field(min_length=2, max_length=120)
    predicted_role_ua: str = Field(min_length=2, max_length=120)
    signal_summary_en: str = Field(min_length=10, max_length=400)
    signal_summary_ua: str = Field(min_length=10, max_length=400)


def _get_with_retry(params: dict, sleep=time.sleep) -> requests.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=25)
        if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
            ra = resp.headers.get("Retry-After", "").strip()
            wait = min(int(ra) if ra.isdigit() else BACKOFF_BASE * 2 ** (attempt - 1), MAX_WAIT)
            sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError("ArXiv: вичерпано спроби")


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    papers = []
    for e in root.findall("atom:entry", NS):
        text = lambda tag: (e.findtext(tag, default="", namespaces=NS) or "").strip().replace("\n", " ")
        abs_url = text("atom:id")
        if not abs_url:
            continue   # без ідентифікатора запис не можна ні дедуплікувати, ні перевірити
        prim = e.find("arxiv:primary_category", NS)
        cat = e.find("atom:category", NS)
        category = (prim if prim is not None else cat)
        papers.append({
            "arxiv_id": abs_url.split("/abs/")[-1],
            "abs_url": abs_url,
            "title": " ".join(text("atom:title").split()),
            "summary": " ".join(text("atom:summary").split()),
            "published": text("atom:published")[:10] or None,
            "category": category.attrib.get("term") if category is not None else None,
        })
    return papers


class ArxivSignals(BaseCollector):
    source = "arxiv"
    fact_table = "fct_arxiv_signals"
    id_column = "arxiv_id"
    on_conflict = "arxiv_id"
    collection_method = "api"
    tracks_presence = False
    collector_version = "2"

    def fetch(self):
        params = {
            "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
            "sortBy": "submittedDate", "sortOrder": "descending",
            "max_results": int(os.getenv("ARXIV_MAX_RESULTS", "5")),
        }
        for p in parse_feed(_get_with_retry(params).content):
            yield RawItem(external_id=p["arxiv_id"], payload=p,
                          content_key=f"{p['title']}|{p['summary']}")

    def parse(self, raw: RawItem) -> dict | None:
        p = raw.payload
        prompt = f"""Analyze this AI preprint and extract the emerging technology trend
for the future tech job market. Base the answer only on the title and abstract.

Return strictly valid JSON:
{{
  "predicted_skill": "global canonical name (e.g. GRPO, Test-Time Compute, Agent Memory)",
  "predicted_role_en": "predicted future job role in English",
  "predicted_role_ua": "та сама роль українською",
  "signal_summary_en": "1 concise sentence: why this is a leading commercial indicator",
  "signal_summary_ua": "1 стисле речення українською: чому це важливо для майбутнього ринку"
}}

Title: {p['title']}
Abstract: {p['summary'][:3000]}
"""
        res = self.llm.extract(prompt=prompt, schema=ArxivSignal, prompt_name="arxiv_signal",
                               prompt_version=PROMPT_VERSION, content_hash=raw.content_hash)
        if res is None:
            return None
        x = res.data
        return {
            "published_date": p["published"],
            "event_date": p["published"],
            "title": p["title"],
            "category": p["category"],
            "predicted_skill": x.predicted_skill,
            "predicted_role": x.predicted_role_en,
            "signal_summary": json.dumps({
                "en": x.signal_summary_en, "ua": x.signal_summary_ua,
                "role_en": x.predicted_role_en, "role_ua": x.predicted_role_ua,
            }, ensure_ascii=False),
            "source_url": p["abs_url"],
            "extraction_method": res.method,
            "prompt_version": PROMPT_VERSION,
        }


if __name__ == "__main__":
    ArxivSignals().run()
