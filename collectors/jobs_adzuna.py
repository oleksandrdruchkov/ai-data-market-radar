"""
collectors/jobs_adzuna.py
Вакансії з Adzuna API (США, Велика Британія; ринки та запити налаштовуються).
Замінює main_pipeline.py.

Важливо: Adzuna повертає лише першу сторінку пошуку, а не повний список ринку,
тому tracks_presence = False - вакансію, що випала з топу видачі, не можна
вважати закритою.

Змінні: ADZUNA_APP_ID, ADZUNA_APP_KEY (обов'язкові)
        ADZUNA_MARKETS="us:US:USD,gb:Europe:GBP"   ADZUNA_QUERY="data engineer python"
        ADZUNA_PER_PAGE=20
Запуск: python -m collectors.jobs_adzuna
"""

from __future__ import annotations

import os

import requests

from core import RawItem
from collectors._jobs_common import JobsCollector

PROMPT_VERSION = "vacancy_v2"
DEFAULT_MARKETS = "us:US:USD,gb:Europe:GBP"


def _markets() -> list[dict]:
    out = []
    for chunk in os.getenv("ADZUNA_MARKETS", DEFAULT_MARKETS).split(","):
        code, region, currency = (p.strip() for p in chunk.split(":"))
        out.append({"country_code": code, "region": region, "currency": currency})
    return out


class AdzunaJobs(JobsCollector):
    source = "adzuna"
    collection_method = "api"
    tracks_presence = False
    collector_version = "2"

    def fetch(self):
        app_id = os.getenv("ADZUNA_APP_ID", "").strip()
        app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
        if not app_id or not app_key:
            raise RuntimeError("Не задано ADZUNA_APP_ID / ADZUNA_APP_KEY")
        query = os.getenv("ADZUNA_QUERY", "data engineer python")
        per_page = int(os.getenv("ADZUNA_PER_PAGE", "20"))

        for m in _markets():
            resp = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/{m['country_code']}/search/1",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": per_page,
                        "what": query, "content-type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()   # помилка ринку = помилка fetch, а не тихі 0 записів
            results = resp.json().get("results", [])
            self.log.info(f"Adzuna {m['country_code'].upper()}: {len(results)} вакансій")
            for item in results:
                title = item.get("title", "")
                company = (item.get("company") or {}).get("display_name", "")
                desc = item.get("description", "")
                yield RawItem(
                    # id Adzuna унікальний лише в межах країни
                    external_id=f"{m['country_code']}:{item.get('id')}",
                    payload={**item, "_market": m, "_query": query},
                    content_key=f"{title}|{company}|{desc}",
                )

    def parse(self, raw: RawItem) -> dict | None:
        item, m = raw.payload, raw.payload["_market"]
        res = self.extract(raw, item.get("title", ""), item.get("description", ""),
                           translate=False, prompt_version=PROMPT_VERSION)
        if res is None:
            return None
        x = res.data
        created = item.get("created")
        return {
            "title": item.get("title") or x.title_en,
            "company": (item.get("company") or {}).get("display_name"),
            "location": (item.get("location") or {}).get("display_name"),
            "region": m["region"],
            "country_code": m["country_code"].upper(),
            "currency": m["currency"],
            "salary_period": "yearly",
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "salary_is_predicted": str(item.get("salary_is_predicted", "0")) == "1",
            "experience_level": x.experience_level,
            "work_model": x.work_model,
            "track": x.track,
            "source_url": item.get("redirect_url"),
            "event_date": created[:10] if created else None,
            "posted_at": created,
            "extraction_method": res.method,
            "prompt_version": PROMPT_VERSION,
            "_skills": x.skills,
        }


if __name__ == "__main__":
    AdzunaJobs().run()
