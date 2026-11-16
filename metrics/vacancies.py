"""
metrics/vacancies.py
Скільки активних вакансій стоїть за графіком навичок при вибраних фільтрах (v_vacancy_counts, sql/031).
Чиста функція, без бази й без Streamlit.
"""

from __future__ import annotations

import pandas as pd


def vacancy_summary(counts: pd.DataFrame | None, region: str = "All Regions", track: str = "All",
                    level: str = "All") -> dict | None:
    """counts: колонки region, source, track, experience_level, vacancies, with_skills.

    Повертає {"total", "with_skills", "by", "parts"}: parts - [(назва, кількість)] за спаданням;
    розбивка (by) - за регіонами, коли вибрано всі регіони, інакше за джерелами.
    None - якщо даних немає або за фільтрами жодної вакансії."""
    if counts is None or counts.empty:
        return None
    c = counts
    if region != "All Regions":
        c = c[c["region"] == region]
    if track != "All":
        c = c[c["track"] == track]
    if level != "All":
        c = c[c["experience_level"] == level]
    total = int(c["vacancies"].sum())
    if total == 0:
        return None
    by = "region" if region == "All Regions" else "source"
    parts = c.groupby(by)["vacancies"].sum().sort_values(ascending=False)
    return {"total": total, "with_skills": int(c["with_skills"].sum()), "by": by,
            "parts": [(str(k), int(v)) for k, v in parts.items()]}
