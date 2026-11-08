"""
core/scales.py
ЄДИНЕ місце, де визначено шкалу SAI_T і її константи.
Користуються: metrics/autonomy.py (значення в базі) і app.py (точки, проєкція, осі на табло).
Змінили еталон чи формулу тут - змінилось усюди.

SAI_T = 100 * log10(1 + T_хв) / log10(124 800)
  100% = еталон «1 людино-рік» = 2 080 год = 124 800 хв;
  шкала логарифмічна: кожне подвоєння горизонту додає однакову кількість відсоткових пунктів.
"""

from __future__ import annotations

import numpy as np

REFERENCE_MIN = 124_800.0                 # 1 людино-рік = 2 080 год
REFERENCE_H = REFERENCE_MIN / 60.0
INSTRUMENT_CEILING_H = 16.0               # найдовші задачі в наборі METR: вище інструмент не вимірює надійно


def sai_t(hours):
    """Години -> SAI_T у %. Приймає число або масив; None/NaN/≤0 -> NaN."""
    h = np.asarray(hours, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 100.0 * np.log10(1.0 + h * 60.0) / np.log10(REFERENCE_MIN)
    out = np.where(h > 0, out, np.nan)
    return float(out) if out.ndim == 0 else out


def hours_at_sai_t(pct):
    """Обернена функція: SAI_T у % -> години."""
    p = np.asarray(pct, dtype=float)
    out = (np.power(10.0, p / 100.0 * np.log10(REFERENCE_MIN)) - 1.0) / 60.0
    return float(out) if out.ndim == 0 else out


def beyond_ceiling(hours) -> bool:
    """Чи вимір вище стелі набору задач METR (тоді це оцінка, а не надійний вимір)."""
    try:
        return float(hours) > INSTRUMENT_CEILING_H
    except (TypeError, ValueError):
        return False
