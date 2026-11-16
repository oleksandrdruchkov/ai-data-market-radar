"""
collectors/jobs_cn_labs.py
Вакансії китайських лабораторій-лідерів, крім DeepSeek (той - collectors/jobs_deepseek.py):
Moonshot (Kimi) і Zhipu (Z.ai) - сторінки найму на MokaHR, MiniMax - на Feishu.

Кожне оголошення читається повністю (назва, опис, місто, дата) і розбирається ключовими
словами, без мовної моделі (collectors/_job_keywords.py). Регіон вакансій - China, окремо від APAC.
Кожна лабораторія - окреме джерело (moonshot_careers, zhipu_careers, minimax_careers), щоб
збій однієї сторінки не закривав вакансії інших.

Feishu: список вакансій - POST <host>/api/v1/search/job/posts (по 100), перед ним сайт видає
токен захисту форми (/api/v1/csrf/token). Лише читання публічних сторінок.

Повнота: зниклі вакансії закриваються лише після повного списку. Лічильник сторінки MokaHR буває
на кілька вакансій більший за список відкритих (до нього входять і не відкриті), тому список
вважається повним, якщо його пройдено до кінця і в ньому не менше 90 % лічильника.

Змінні: CN_LABS="moonshot,zhipu,minimax"  (які лабораторії збирати)
Запуск: python -m collectors.jobs_cn_labs            (запис у базу)
        python -m collectors.jobs_cn_labs --dry-run  (лише друк розібраного, без бази)
"""

from __future__ import annotations

import os
import re
import sys
import html as htmllib
from datetime import datetime, timezone
from urllib.parse import unquote

from core import RawItem
from collectors import _job_keywords as keywords
from collectors._jobs_common import JobsCollector
from collectors.jobs_deepseek import HEADERS, MAX_PAGES, PAGE_SIZE, cn_vacancy_fact, fetch_all as moka_fetch_all

MOKA_MAX = MAX_PAGES * PAGE_SIZE      # більше за стільки вакансій список MokaHR не читається

FEISHU_PAGE = 100
FEISHU_MAX_PAGES = 10
TAG_RE = re.compile(r"<[^>]+>")


def _clean(v) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", htmllib.unescape(v))).strip() if isinstance(v, str) else ""


def feishu_payload(job: dict, base: str, path: str, company: str) -> dict:
    """Чиста функція: вакансія зі списку Feishu -> payload того самого вигляду, що й для MokaHR."""
    cities = job.get("city_list") or ([job["city_info"]] if isinstance(job.get("city_info"), dict) else [])
    names = [c.get("name") for c in cities if isinstance(c, dict) and c.get("name")]
    ts = job.get("publish_time")
    posted = None
    if isinstance(ts, (int, float)) and ts > 0:
        posted = datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc).date().isoformat()
    cat = job.get("job_category") if isinstance(job.get("job_category"), dict) else {}
    recruit = job.get("recruit_type") if isinstance(job.get("recruit_type"), dict) else {}
    desc = "\n".join(x for x in (_clean(job.get("description")), _clean(job.get("requirement"))) if x)
    return {
        "id": str(job["id"]),
        "title": (job.get("title") or "").strip(),
        "description": desc,
        "category": " ".join(x for x in (cat.get("name"), recruit.get("name")) if x) or None,
        "location": " / ".join(dict.fromkeys(names)) or None,
        "company": company,
        "url": f"{base}/{path}/position/{job['id']}/detail",
        "posted_date": posted,
    }


def feishu_fetch_all(host: str, path: str, company: str, session=None) -> tuple[list[dict], int | None]:
    """Усі вакансії сторінки Feishu. Повертає (вакансії, лічильник сторінки)."""
    import requests
    base = f"https://{host}"
    s = session or requests.Session()
    s.headers.update({**HEADERS, "website-path": path, "Referer": f"{base}/{path}", "Origin": base})
    r = s.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1}, timeout=60)
    r.raise_for_status()
    token = s.cookies.get("atsx-csrf-token") or ((r.json().get("data") or {}).get("token"))
    if not token:
        raise ValueError("Feishu: сайт не видав токен захисту форми")
    seen: dict[str, dict] = {}
    total = None
    for n in range(FEISHU_MAX_PAGES):
        q = {"keyword": "", "limit": FEISHU_PAGE, "offset": n * FEISHU_PAGE, "portal_type": 6, "portal_entrance": 1}
        r = s.post(f"{base}/api/v1/search/job/posts", params=q, json=q,
                   headers={"x-csrf-token": unquote(token)}, timeout=60)
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise ValueError(f"Feishu відповів помилкою: {str(body)[:200]}")
        data = body.get("data") or {}
        total = data.get("count") if isinstance(data.get("count"), int) else total
        batch = data.get("job_post_list") or []
        for j in batch:
            if isinstance(j, dict) and j.get("id") and (j.get("title") or "").strip():
                seen.setdefault(str(j["id"]), feishu_payload(j, base, path, company))
        if len(batch) < FEISHU_PAGE or (total is not None and len(seen) >= total):
            break
    return list(seen.values()), total


def moka_complete(n_jobs: int, total: int | None, mode: str) -> bool:
    """Чиста функція: чи список MokaHR повний (див. «Повнота» вгорі)."""
    if mode != "api" or n_jobs >= MOKA_MAX:
        return False
    return total is None or n_jobs >= 0.9 * total


class LabJobs(JobsCollector):
    """Спільне для лабораторій: повний список сторінки найму -> розбір ключовими словами."""
    collection_method = "scrape"
    tracks_presence = True
    collector_version = "1"
    company = ""
    platform = ""

    def load(self) -> tuple[list[dict], int | None, bool]:
        """(вакансії, лічильник сторінки, чи список повний)."""
        raise NotImplementedError

    def fetch(self):
        jobs, total, complete = self.load()
        with_desc = sum(1 for j in jobs if j.get("description") and not j["description"].startswith("职能："))
        self.log.info(f"{self.company} ({self.platform}): відкритих вакансій {len(jobs)}, "
                      f"за лічильником сторінки {total}, з описом {with_desc}")
        if not jobs:
            raise ValueError(f"{self.company}: список вакансій порожній - підозріло, нічого не закриваємо")
        if not complete:
            self.tracks_presence = False
            self.log.warning("Зібрано не всі вакансії: зниклі в цьому запуску не закриваються")
        for job in jobs:
            yield RawItem(external_id=str(job["id"]), payload={**job, "_origin": self.platform},
                          content_key=f"{job['title']}|{job.get('company', '')}|{job.get('description', '')}"
                                      f"|{keywords.KEYWORDS_VERSION}")

    def parse(self, raw: RawItem) -> dict | None:
        return cn_vacancy_fact(raw.payload, self.company)


class MokaLabJobs(LabJobs):
    platform = "mokahr"
    org = ""
    site = ""

    def load(self):
        jobs, total, mode = moka_fetch_all(log=self.log, org=self.org, site=self.site, company=self.company)
        return jobs, total, moka_complete(len(jobs), total, mode)


class MoonshotJobs(MokaLabJobs):
    source = "moonshot_careers"
    company, org, site = "Moonshot", "moonshot", "148506"


class ZhipuJobs(MokaLabJobs):
    source = "zhipu_careers"
    company, org, site = "Zhipu", "zphz", "148983"


class MiniMaxJobs(LabJobs):
    source = "minimax_careers"
    platform = "feishu"
    company = "MiniMax"
    host, path = "vrfi1sk8a0.jobs.feishu.cn", "379481"

    def load(self):
        jobs, total = feishu_fetch_all(self.host, self.path, self.company)
        return jobs, total, total is None or len(jobs) >= total


LABS = {"moonshot": MoonshotJobs, "zhipu": ZhipuJobs, "minimax": MiniMaxJobs}


def lab_keys() -> list[str]:
    raw = [k.strip().lower() for k in os.getenv("CN_LABS", ",".join(LABS)).split(",") if k.strip()]
    unknown = [k for k in raw if k not in LABS]
    if unknown:
        raise ValueError(f"CN_LABS: невідомі лабораторії {unknown}; відомі: {sorted(LABS)}")
    return raw


def dry_run() -> int:
    import logging
    from collections import Counter
    logging.basicConfig(level=logging.INFO)
    bad = 0
    for key in lab_keys():
        cls = LABS[key]
        c = cls.__new__(cls)
        c.log = logging.getLogger(f"dry-run.{key}")
        try:
            jobs, total, complete = c.load()
        except Exception as e:
            print(f"\n=== {cls.company}: ПОМИЛКА {type(e).__name__}: {str(e)[:200]}")
            bad += 1
            continue
        facts = [cn_vacancy_fact(j, cls.company) for j in jobs]
        skills = Counter(s.name for f in facts for s in f["_skills"])
        print(f"\n=== {cls.company}: зібрано {len(jobs)}, лічильник {total}, повний список: {complete}, "
              f"з описом {sum(1 for j in jobs if len(j.get('description') or '') > 80)}, "
              f"з навичками {sum(1 for f in facts if f['_skills'])}, з датою {sum(1 for j in jobs if j.get('posted_date'))}, "
              f"з містом {sum(1 for j in jobs if j.get('location'))}")
        print("  напрями:", dict(Counter(f["track"] for f in facts).most_common()))
        print("  рівні:", dict(Counter(f["experience_level"] for f in facts).most_common()))
        print("  навички:", ", ".join(f"{n} {c}" for n, c in skills.most_common(25)))
        other = [f["title"] for f in facts if f["track"] == "Other"][:12]
        print("  без напряму (Other):", " | ".join(other))
        for j, f in list(zip(jobs, facts))[:4]:
            print(f"  - {j.get('posted_date')} | {j['title']} | {j.get('location')} | {j.get('category')} | "
                  f"{f['track']} / {f['experience_level']} | {[s.name for s in f['_skills']]} | {(j.get('description') or '')[:90]}")
    return 1 if bad else 0


def main() -> int:
    """Лабораторії збираються по черзі; критична помилка однієї не зупиняє інші, але робить крок червоним."""
    failed = 0
    for key in lab_keys():
        try:
            LABS[key]().run()
        except SystemExit as e:
            failed += 1 if e.code else 0
        except Exception as e:
            print(f"{key}: {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(dry_run() if "--dry-run" in sys.argv else main())
