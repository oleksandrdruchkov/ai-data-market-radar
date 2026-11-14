"""
collectors/jobs_deepseek.py
Вакансії DeepSeek (High-Flyer, Китай, APAC) з офіційної сторінки на MokaHR:
https://app.mokahr.com/social-recruitment/high-flyer/140576

Як працює:
  1) сторінка: вбудовані дані - aesIv (вектор розшифрування) і jobStats.total (скільки вакансій);
     у HTML вбудовано лише першу сторінку списку (15) і без описів;
  2) список по сторінках: POST /api/outer/ats-apply/website/jobs/v2 {orgId, siteId, limit, offset}.
     Відповідь зашифрована так само, як у браузері: {"data", "necromancer"} ->
     AES-CBC, ключ = necromancer, iv = aesIv, PKCS7 (функція we() у скрипті застосунку).
     У розшифрованих вакансіях є повний опис (jobDescription) і місто.
  Якщо запит списку не вдався - запасний режим: 15 вбудованих вакансій без опису.
Переклад і розбір навичок - core.llm (prompt vacancy_zh_v2).

Повнота: зібрано менше, ніж jobStats.total, - список неповний, зниклі вакансії не закриваються.

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
import time
import base64
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
JOBS_API = "https://app.mokahr.com/api/outer/ats-apply/website/jobs/v2"
PAGE_SIZE = 15
MAX_PAGES = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketRadarBot/2.0; "
                         "+https://github.com/oleksandrdruchkov/ai-data-market-radar)",
           "Accept-Language": "zh-CN,zh;q=0.9"}

DESC_KEYS = ("jobDescription", "description", "content", "desc", "responsibility",
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


def decrypt(data_b64: str, key: str, iv: str) -> str:
    """Чиста функція: розшифрування відповіді MokaHR (як we() у браузері): AES-CBC, PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    d = Cipher(algorithms.AES(key.encode("utf-8")), modes.CBC(iv.encode("utf-8"))).decryptor()
    raw = d.update(base64.b64decode(data_b64)) + d.finalize()
    u = padding.PKCS7(128).unpadder()
    return (u.update(raw) + u.finalize()).decode("utf-8")


def open_response(body: dict, iv: str) -> dict:
    """Відповідь API -> розшифрований dict; помилка MokaHR (success=false, code != 0) - виняток."""
    if isinstance(body, dict) and body.get("necromancer") and isinstance(body.get("data"), str):
        body = json.loads(decrypt(body["data"], body["necromancer"], iv))
    if not isinstance(body, dict) or body.get("code", 0) != 0 or body.get("success") is False:
        raise ValueError(f"MokaHR відповів помилкою: {str(body)[:200]}")
    return body.get("data", body)


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
                place = "".join(x for x in (it.get("provinceName"), it.get("cityName")) if isinstance(x, str))
                if place.strip():                                      # «北京市海淀区», а не адреса офісу
                    names.append(place.strip())
                    continue
                for kk in ("city", "name", "address"):
                    if isinstance(it.get(kk), str) and it[kk].strip():
                        names.append(it[kk].strip())
                        break
    out = list(dict.fromkeys(names))
    return " / ".join(out) or None


def job_category(job: dict) -> str | None:
    """Категорія вакансії на сторінці (zhineng): «深度学习», «AI核心系统研发» тощо."""
    z = job.get("zhineng")
    if isinstance(z, dict):
        return z.get("label") or z.get("name")
    if isinstance(z, list):
        names = [x.get("label") or x.get("name") for x in z if isinstance(x, dict)]
        return " / ".join(n for n in names if n) or None
    return z if isinstance(z, str) else None


def to_payload(job: dict) -> dict:
    date = (job.get("openedAt") or job.get("createdAt") or "")[:10] or None
    desc = job_description(job)
    if not desc:
        # Список не містить опису (він приходить окремим зашифрованим запитом) - Gemini
        # отримує хоча б категорію і тип зайнятості.
        desc = "；".join(x for x in (f"职能：{job_category(job)}" if job_category(job) else "",
                                      f"类型：{job.get('commitment')}" if job.get("commitment") else "") if x)
    return {
        "id": job["id"],
        "title": job.get("title") or "",
        "description": desc,
        "category": job_category(job),
        "location": job_location(job),
        "company": "DeepSeek",
        "url": f"{PAGE}#/job/{job['id']}",
        "posted_date": date,
        "commitment": job.get("commitment"),
        "updated_at": job.get("updatedAt"),
    }


def open_jobs(raw_jobs: list) -> list[dict]:
    return [to_payload(j) for j in raw_jobs
            if isinstance(j, dict) and j.get("id") and j.get("status", "open") == "open"]


def parse_page(page: str) -> tuple[list[dict], int | None]:
    """Чиста функція: (відкриті вбудовані вакансії як payload, jobStats.total)."""
    state = embedded_state(page)
    total = (state.get("jobStats") or {}).get("total")
    return open_jobs(state["jobs"]), (int(total) if str(total).isdigit() else None)


def fetch_all(session=None, sleep=time.sleep, log=None) -> tuple[list[dict], int | None, str]:
    """Усі відкриті вакансії з описами. Повертає (вакансії, total, режим «api» | «embedded»)."""
    import requests
    s = session or requests.Session()
    s.headers.update({**HEADERS, "Referer": PAGE})
    page = get_with_retry(PAGE, headers=HEADERS, timeout=60).text
    state = embedded_state(page)
    embedded, total = parse_page(page)
    iv = state.get("aesIv") or ""
    try:
        if not iv:
            raise ValueError("на сторінці немає aesIv")
        seen: dict[str, dict] = {}
        for n in range(MAX_PAGES):
            if n:
                sleep(2)
            resp = s.post(JOBS_API, json={"orgId": ORG, "siteId": int(SITE), "limit": PAGE_SIZE,
                                          "offset": n * PAGE_SIZE}, timeout=60)
            resp.raise_for_status()
            batch = open_response(resp.json(), iv).get("jobs") or []
            for j in open_jobs(batch):
                seen.setdefault(j["id"], j)
            if len(batch) < PAGE_SIZE or (total and len(seen) >= total):
                break
        if not seen:
            raise ValueError("API повернув порожній список")
        return list(seen.values()), total, "api"
    except Exception as e:
        if log:
            log.warning(f"Список через API не отримано ({type(e).__name__}: {e}); беру {len(embedded)} вбудованих без опису")
        return embedded, total, "embedded"


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
            jobs, total, mode = fetch_all(log=self.log)
            self.log.info(f"MokaHR ({mode}): відкритих вакансій {len(jobs)}, за лічильником сторінки {total}, "
                          f"з описом {sum(1 for j in jobs if j['description'] and not j['description'].startswith('职能：'))}")
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
    import logging
    logging.basicConfig(level=logging.INFO)
    jobs, total, mode = fetch_all(log=logging.getLogger("dry-run"))
    full = [j for j in jobs if j["description"] and not j["description"].startswith("职能：")]
    print(f"Режим: {mode}; відкритих: {len(jobs)}, за лічильником: {total}; "
          f"з повним описом: {len(full)}, з місцем: {sum(1 for j in jobs if j['location'])}")
    for j in jobs[:8]:
        print(f"- {j['posted_date']} | {j['title']} | {j['location']} | {j['category']} | {j['description'][:120]}")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        dry_run()
    else:
        DeepSeekJobs().run()
