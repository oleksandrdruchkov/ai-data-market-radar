"""Рядок під графіком навичок: скільки вакансій стоїть за вибраними фільтрами."""

import pandas as pd

from metrics.vacancies import vacancy_summary

ROWS = pd.DataFrame([
    {"region": "China", "source": "zhipu_careers", "track": "Machine Learning", "experience_level": "Senior", "vacancies": 30, "with_skills": 30},
    {"region": "China", "source": "zhipu_careers", "track": "Other", "experience_level": "Not Specified", "vacancies": 80, "with_skills": 0},
    {"region": "China", "source": "minimax_careers", "track": "Machine Learning", "experience_level": "Junior", "vacancies": 45, "with_skills": 40},
    {"region": "US", "source": "adzuna", "track": "Data Engineering", "experience_level": "Senior", "vacancies": 38, "with_skills": 37},
])


def test_region_breaks_down_by_source():
    s = vacancy_summary(ROWS, "China")
    assert (s["total"], s["with_skills"], s["by"]) == (155, 70, "source")
    assert s["parts"] == [("zhipu_careers", 110), ("minimax_careers", 45)]


def test_all_regions_break_down_by_region_and_filters_apply():
    s = vacancy_summary(ROWS)
    assert s["by"] == "region" and s["parts"] == [("China", 155), ("US", 38)] and s["total"] == 193
    s = vacancy_summary(ROWS, "China", track="Machine Learning", level="Junior")
    assert s["total"] == 45 and s["parts"] == [("minimax_careers", 45)]


def test_nothing_to_show():
    assert vacancy_summary(ROWS, "Europe") is None
    assert vacancy_summary(pd.DataFrame()) is None and vacancy_summary(None) is None
