"""
collectors/_jobs_common.py
Спільне для всіх збирачів вакансій: схема відповіді LLM, довідник навичок,
запис зв'язків вакансія-навичка. Кожне джерело вакансій (Adzuna, DeepSeek, ...)
успадковує JobsCollector і пише лише fetch() та parse().
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core import BaseCollector

Level = Literal["Junior", "Mid", "Senior", "Lead/Staff", "Not Specified"]
Track = Literal["Data Engineering", "Machine Learning", "Analytics Engineering",
                "Backend", "AI Alignment", "Other"]
WorkModel = Literal["Remote", "Hybrid", "On-site", "Not Specified"]

SKILL_CATEGORIES = (
    "Language", "Deep Learning Framework", "AI Hardware/Kernel", "Post-training",
    "AI Serving", "Applied AI", "Data Platform", "Database", "Cloud", "DevOps", "Tool",
)

LEVELS = " | ".join(f'"{x}"' for x in Level.__args__)
TRACKS = " | ".join(f'"{x}"' for x in Track.__args__)
WORK_MODELS = " | ".join(f'"{x}"' for x in WorkModel.__args__)
CATEGORIES = " | ".join(f'"{x}"' for x in SKILL_CATEGORIES)


class Skill(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category: str = "Tool"

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("порожня назва навички")
        return v

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        # Невідома категорія не ламає запис: це довідникова дрібниця, а не факт
        return v if v in SKILL_CATEGORIES else "Tool"


class VacancyExtraction(BaseModel):
    title_en: str = Field(min_length=2, max_length=200)
    experience_level: Level
    work_model: WorkModel = "Not Specified"
    track: Track
    skills: list[Skill] = Field(default_factory=list, max_length=30)


def vacancy_prompt(title: str, description: str, *, translate: bool) -> str:
    lang = ("The text may be in Chinese or another language. Translate the title and "
            "requirements into standard English industry terms.\n" if translate else "")
    return f"""You are a technical analyst of the Data/AI job market.
{lang}Extract only what is stated or clearly implied in the vacancy. Do not guess:
if the seniority or work model is not stated, use "Not Specified".

Return strictly valid JSON:
{{
  "title_en": "standard English job title",
  "experience_level": {LEVELS},
  "work_model": {WORK_MODELS},
  "track": {TRACKS},
  "skills": [{{"name": "canonical English technology name, e.g. PyTorch, CUDA, Kubernetes", "category": {CATEGORIES}}}]
}}

Title: {title}
Description: {description}
"""


class JobsCollector(BaseCollector):
    fact_table = "fct_vacancies"
    on_conflict = "external_id,source"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._skill_cache: dict[str, int] = {}

    # ---------- допоміжне для parse() ----------

    def extract(self, raw, title: str, description: str, *, translate: bool,
                prompt_version: str):
        return self.llm.extract(
            prompt=vacancy_prompt(title, description[:4000], translate=translate),
            schema=VacancyExtraction,
            prompt_name="vacancy",
            prompt_version=prompt_version,
            content_hash=raw.content_hash,
        )

    # ---------- навички ----------

    def resolve_skill_id(self, name: str, category: str) -> int:
        key = name.strip().lower()
        if key in self._skill_cache:
            return self._skill_cache[key]

        rows = self.db.select("dim_skill_aliases", "skill_id", ilike={"alias": name}, limit=1)
        if not rows:
            rows = self.db.select("dim_skills", "skill_id", ilike={"canonical_name": name}, limit=1)
        if not rows:
            rows = self.db.upsert("dim_skills", {"canonical_name": name, "category": category},
                                  on_conflict="canonical_name")
        if not rows:
            rows = self.db.select("dim_skills", "skill_id", eq={"canonical_name": name}, limit=1)
        skill_id = int(rows[0]["skill_id"])
        self._skill_cache[key] = skill_id
        return skill_id

    # ---------- запис ----------

    def save(self, fact: dict, raw, raw_id: int) -> None:
        skills = fact.pop("_skills", [])
        rows = self.db.upsert(self.fact_table, fact, on_conflict=self.on_conflict)
        if not rows:
            raise RuntimeError("upsert вакансії не повернув рядок")
        vacancy_id = rows[0].get("vacancy_id") or rows[0].get("id")

        skill_ids = sorted({self.resolve_skill_id(s.name, s.category) for s in skills})
        if skill_ids:
            self.db.upsert("bridge_vacancy_skills",
                           [{"vacancy_id": vacancy_id, "skill_id": sid} for sid in skill_ids],
                           on_conflict="vacancy_id,skill_id", ignore_duplicates=True)
        # Якщо текст вакансії змінився, прибираємо навички, яких у ній більше немає
        self.db.delete_not_in("bridge_vacancy_skills", eq={"vacancy_id": vacancy_id},
                              column="skill_id", keep=skill_ids)
