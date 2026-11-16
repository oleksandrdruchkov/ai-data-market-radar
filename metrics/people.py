"""
metrics/people.py
Лінія «Фахівці ШІ» головного графіка: одна лінія за всіма країнами Indeed AI Tracker.

Indeed публікує для кожної країни частку вакансій зі згадкою ШІ, але не кількість вакансій,
тому скласти країни в один світовий обсяг або зважити їх за розміром ринку неможливо.
Лінія - середнє геометричне зростання країн відносно базового місяця, рівна вага:
для кожної країни «частка в місяці / частка в базовому місяці», далі середнє геометричне
цих відношень (на логарифмічній осі воно не дає одній країні зі стрибком перетягнути лінію).

Чисті функції, без бази й без Streamlit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def people_growth(monthly: pd.DataFrame, base_month: pd.Timestamp) -> dict:
    """monthly: колонки region, month, value (середня частка за місяць, %).

    Повертає:
      mult      Series місяць -> у скільки разів (середнє геометричне країн), з базового місяця
      low/high  найменше й найбільше зростання серед країн у цей місяць
      n         скільки країн у розрахунку в цей місяць
      regions   країни, що мають значення в базовому місяці (лише вони в розрахунку)
      latest    {країна: зростання в останньому місяці}
    Країна без додатного значення в базовому місяці не враховується."""
    empty = {"mult": pd.Series(dtype=float), "low": pd.Series(dtype=float), "high": pd.Series(dtype=float),
             "n": pd.Series(dtype=int), "regions": [], "latest": {}}
    if monthly is None or monthly.empty:
        return empty
    wide = monthly.pivot_table(index="month", columns="region", values="value", aggfunc="mean").sort_index()
    if base_month not in wide.index:
        return empty
    base = wide.loc[base_month]
    regions = sorted(base[base > 0].index)
    if not regions:
        return empty
    ratio = wide.loc[wide.index >= base_month, regions] / base[regions]
    ratio = ratio.where(ratio > 0)
    n = ratio.notna().sum(axis=1)
    ratio = ratio[n > 0]
    mult = np.exp(np.log(ratio).mean(axis=1, skipna=True))
    last = ratio.iloc[-1].dropna()
    return {"mult": mult, "low": ratio.min(axis=1), "high": ratio.max(axis=1), "n": n[n > 0],
            "regions": regions, "latest": {r: float(v) for r, v in last.items()}}


def cn_labs_bars(rows: pd.DataFrame, max_daily: int = 14, max_bars: int = 12) -> tuple[pd.DataFrame, str]:
    """Відкриті вакансії китайських лабораторій для стовпчиків у часі.

    rows: колонки lab, day, value (знімок на дату). Повертає (таблиця: рядок - період, колонка -
    лабораторія; режим «day» | «week»).
    Поки дат не більше max_daily - стовпчик на кожну дату; далі - на тиждень (останній знімок тижня),
    і лише останні max_bars тижнів, щоб графік читався на телефоні.
    У таблицю входять лише дати, коли відповіли всі лабораторії, що є в даних: стовпчик без однієї
    лабораторії виглядав би як падіння найму."""
    if rows is None or rows.empty:
        return pd.DataFrame(), "day"
    wide = rows.pivot_table(index="day", columns="lab", values="value", aggfunc="last").sort_index()
    wide = wide.dropna(how="any")
    if wide.empty or len(wide) <= max_daily:
        return wide, "day"
    weekly = wide.groupby(wide.index.to_period("W-SUN")).tail(1)
    return weekly.tail(max_bars), "week"
