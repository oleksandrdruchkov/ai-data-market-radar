"""
collectors/jobs_deepseek.py
Вакансії DeepSeek (High-Flyer, Китай, APAC) з офіційної сторінки на MokaHR:
https://app.mokahr.com/social-recruitment/high-flyer/140576

Сторінка вбудовує список вакансій прямо в HTML (JSON у атрибуті сторінки: ключі jobs,
jobStats.total ...), тож береться один запит на сторінку - без внутрішніх API, відповіді
яких MokaHR шифрує. Переклад і розбір навичок - core.llm (prompt vacancy_zh_v2).

Повнота: якщо вбудовано менше вакансій, ніж jobStats.total, список вважається неповним
і зниклі вакансії в цьому запуску не закриваються.

Попередня версія читала три вакансії з collectors/seeds/deepseek_manual.json; вони мають
інші id і закриються першим повним запуском (is_active = false). Ручний список лишився
запасним варіантом: DEEPSEEK_SEED_FILE=<шлях>.

Змінні: MOKA_ORG="high-flyer"  MOKA_SITE="140576"
Запуск: python -m collectors.jobs_deepseek            (запис у базу)
        python -m collectors.jobs_deepseek --dry-run  (лише друк розібраного, без бази)
"""

from __future__ import annotations

import os
import re
import sys
import json
import html as htmllib
from pathlib import Path

from core import RawItem
from core.http import get_with_retry
from collectors._jobs_common import JobsCollector

SEED_FILE = Path(__file__).parent / "seeds" / "deepseek_manual.json"
PROMPT_VERSION = "vacancy_zh_v2"
ORG = os.getenv("MOKA_ORG", "high-flyer")
SITE = os.getenv("MOKA_SITE", "140576")
PAGE = f"https://app.mokahr.com/social-recruitment/{ORG}/{SITE}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketRadarBot/2.0; "
                         "+https://github.com/oleksandrdruchkov/ai-data-market-radar)",
           "Accept-Language": "zh-CN,zh;q=0.9"}

DESC_KEYS = ("description", "jobDescription", "content", "desc", "responsibility",
             "jobResponsibility", "requirement", "jobRequirement")
TAG_RE = re.compile(r"<[^>]+>")


def embedded_state(page: str) -> dict:
    """Чиста функція: вбудований у HTML JSON сторінки, у якому є ключ jobs."""
    for blob in re.findall(r"""=\s*["']({&quot;.*?})["']""", page, re.S):
        try:
            data = json.loads(htmllib.unescape(blob))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data
    raise ValueError("MokaHR: у сторінці немає вбудованого списку jobs - змінився формат")


def _text(v) -> str:
    if isinstance(v, str):
        return re.sub(r"\s+", " ", TAG_RE.sub(" ", htmllib.unescape(v))).strip()
    return ""


def job_description(job: dict) -> str:
    parts = [_text(job.get(k)) for k in DESC_KEYS]
    return "\n".join(p for p in parts if p)


def job_location(job: dict) -> str | None:
    names: list[str] = []
    for k, v in job.items():
        if not re.search(r"location|city", k, re.I):
            continue
        items = v if isinstance(v, list) else [v]
        for it in items:
            if isinstance(it, str) and it.strip():
                names.append(it.strip())
            elif isinstance(it, dict):
                for kk in ("address", "cityName", "city", "name"):
                    if isinstance(it.get(kk), str) and it[kk].strip():
                        names.append(it[kk].strip())
                        break
    out = list(dict.fromkeys(names))
    return " / ".join(out) or None


def to_payload(job: dict) -> dict:
    date = (job.get("openedAt") or job.get("createdAt") or "")[:10] or None
    return {
        "id": job["id"],
        "title": job.get("title") or "",
        "description": job_description(job),
        "location": job_location(job),
        "company": "DeepSeek",
        "url": f"{PAGE}#/job/{job['id']}",
        "posted_date": date,
        "commitment": job.get("commitment"),
        "updated_at": job.get("updatedAt"),
    }


def parse_page(page: str) -> tuple[list[dict], int | None]:
    """Чиста функція: (відкриті вакансії як payload, jobStats.total)."""
    state = embedded_state(page)
    jobs = [to_payload(j) for j in state["jobs"]
            if isinstance(j, dict) and j.get("id") and j.get("status", "open") == "open"]
    total = (state.get("jobStats") or {}).get("total")
    return jobs, (int(total) if isinstance(total, (int, float, str)) and str(total).isdigit() else None)


class DeepSeekJobs(JobsCollector):
    source = "deepseek_careers"
    collection_method = "scrape"
    tracks_presence = True        # сторінка дає повний список; неповний - вимикається в fetch()
    collector_version = "3"

    def fetch(self):
        seed = os.getenv("DEEPSEEK_SEED_FILE")
        if seed:
            self.log.warning(f"Запасний режим: ручний список {seed}")
            jobs = json.loads(Path(seed).read_text(encoding="utf-8"))
        else:
            page = get_with_retry(PAGE, headers=HEADERS, timeout=60).text
            jobs, total = parse_page(page)
            self.log.info(f"MokaHR: відкритих вакансій {len(jobs)}, за лічильником сторінки {total}")
            if not jobs:
                raise ValueError("MokaHR: список вакансій порожній - підозріло, нічого не закриваємо")
            if total is not None and len(jobs) < total:
                self.tracks_presence = False
                self.log.warning("Вбудовано не всі вакансії: зниклі в цьому запуску не закриваються")
        for job in jobs:
            yield RawItem(
                external_id=str(job["id"]),
                payload={**job, "_origin": "manual_seed" if seed else "mokahr"},
                content_key=f"{job['title']}|{job.get('company', '')}|{job.get('description', '')}",
            )

    def parse(self, raw: RawItem) -> dict | None:
        job = raw.payload
        res = self.extract(raw, job["title"], job.get("description") or job["title"], translate=True,
                           prompt_version=PROMPT_VERSION)
        if res is None:
            return None
        x = res.data
        return {
            "title": x.title_en,
            "title_original": job["title"],
            "company": job.get("company", "DeepSeek"),
            "location": job.get("location"),
            "region": "APAC",
            "country_code": "CN",
            "currency": "CNY",
            "salary_period": "yearly",
            "experience_level": x.experience_level,
            "work_model": x.work_model,
            "track": x.track,
            "source_url": job.get("url"),
            "event_date": job.get("posted_date"),   # дата відкриття вакансії на сторінці, не дата збору
            "extraction_method": res.method,
            "prompt_version": PROMPT_VERSION,
            "_skills": x.skills,
        }


def dry_run() -> None:
    page = get_with_retry(PAGE, headers=HEADERS, timeout=60).text
    state = embedded_state(page)
    raw_jobs = state["jobs"]
    print(f"Вбудовано вакансій: {len(raw_jobs)}, jobStats.total: {(state.get('jobStats') or {}).get('total')}")
    if raw_jobs:
        print(f"Ключі першої вакансії: {sorted(raw_jobs[0])}")
    jobs, _ = parse_page(page)
    with_desc = sum(1 for j in jobs if j["description"])
    print(f"Відкритих: {len(jobs)}, з описом: {with_desc}, з місцем: {sum(1 for j in jobs if j['location'])}")
    for j in jobs[:8]:
        print(f"- {j['posted_date']} | {j['title']} | {j['location']} | {j['description'][:150]}")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        dry_run()
    else:
        DeepSeekJobs().run()
