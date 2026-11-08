"""
collectors/jobs_deepseek.py
Вакансії DeepSeek / High-Flyer (Китай, APAC): переклад і розбір навичок через core.llm.

УВАГА: живого джерела поки немає. Попередня версія мала три вакансії, вписані в код;
тепер вони винесені в collectors/seeds/deepseek_manual.json і позначаються
collection_method = "manual_seed", source_url = NULL, event_date = NULL.
Коли знайдемо офіційну сторінку вакансій із придатною структурою, замінимо fetch()
на справжній запит, а решта збирача не зміниться.

Запуск:  python -m collectors.jobs_deepseek
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core import RawItem
from collectors._jobs_common import JobsCollector

SEED_FILE = Path(__file__).parent / "seeds" / "deepseek_manual.json"
PROMPT_VERSION = "vacancy_zh_v2"


class DeepSeekJobs(JobsCollector):
    source = "deepseek_careers"
    collection_method = "manual_seed"
    tracks_presence = True        # файл містить повний список, тож зниклі можна закривати
    collector_version = "2"

    def fetch(self):
        path = Path(os.getenv("DEEPSEEK_SEED_FILE", SEED_FILE))
        self.log.warning(f"Живого джерела немає: читаю ручний список {path.name}")
        for job in json.loads(path.read_text(encoding="utf-8")):
            yield RawItem(
                external_id=str(job["id"]),
                payload={**job, "_origin": "manual_seed"},
                content_key=f"{job['title']}|{job.get('company', '')}|{job['description']}",
            )

    def parse(self, raw: RawItem) -> dict | None:
        job = raw.payload
        res = self.extract(raw, job["title"], job["description"], translate=True,
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
            "source_url": job.get("url"),          # у ручному списку немає
            "event_date": job.get("posted_date"),  # дата публікації, якщо відома; не дата збору
            "extraction_method": res.method,
            "prompt_version": PROMPT_VERSION,
            "_skills": x.skills,
        }


if __name__ == "__main__":
    DeepSeekJobs().run()
