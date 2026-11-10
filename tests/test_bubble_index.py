"""metrics/bubble.py: бали без знання майбутнього і зведений індекс."""

from __future__ import annotations

import numpy as np
import pandas as pd

from metrics import bubble


def test_expanding_score_no_lookahead():
    s = pd.Series([1.0, 2.0, 3.0, 2.0, 10.0], index=pd.date_range("2022-01-01", periods=5))
    up = bubble.expanding_score(s, +1, min_history=3)
    assert np.isnan(up.iloc[0]) and np.isnan(up.iloc[1])
    assert list(up.iloc[2:]) == [100.0, 75.0, 100.0]      # 2.0 серед [1,2,3,2] -> 3/4
    down = bubble.expanding_score(s, -1, min_history=3)
    assert list(down.iloc[2:]) == [33.33, 75.0, 20.0]
    # майбутнє не впливає на минуле
    longer = pd.concat([s, pd.Series([0.0], index=[pd.Timestamp("2022-01-06")])])
    assert list(bubble.expanding_score(longer, +1, 3).iloc[2:5]) == list(up.iloc[2:])


def _series(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values)), dtype=float)


def test_build_scores_and_rows():
    n = 300
    raw = {
        "fred_baa10y": _series(np.linspace(1, 3, n)),                 # росте -> бал 100
        "fred_ust10y": _series(np.linspace(3, 1, n)),                 # падає -> бал низький
        "indeed_softdev_postings": _series(np.linspace(100, 50, n)),
        "indeed_total_postings": _series([100.0] * n),                # розробників менше -> бал 100
    }
    df = bubble.build_scores(raw, min_history=10)
    last = df.iloc[-1]
    assert last["bubble_score_credit"] == 100.0 and last["bubble_score_devjobs"] == 100.0
    assert last["bubble_score_rate10y"] < 1
    assert last["_n"] == 3 and abs(last["bubble_fragility"] - (200 + last["bubble_score_rate10y"]) / 3) < 0.01
    assert "bubble_score_hy" not in df                                # немає вхідного ряду - немає балу
    rows = bubble.to_rows(df.tail(1), run_id=7)
    fr = [r for r in rows if r["metric_id"] == "bubble_fragility"][0]
    assert fr["numerator"] == 3 and fr["denominator"] == len(bubble.COMPONENTS) and fr["region"] == "US"


def test_fragility_needs_two_components():
    df = bubble.build_scores({"fred_baa10y": _series(np.linspace(1, 2, 50))}, min_history=10)
    assert df["bubble_fragility"].isna().all()


def test_long_gap_restarts_history():
    s = _series([1.0] * 20 + [np.nan] * 30 + [2.0] * 20)
    df = bubble.build_scores({"fred_baa10y": s.dropna(), "fred_ust10y": _series([1.0] * 70)}, min_history=5)
    first = df["bubble_score_credit"].first_valid_index()
    assert first >= pd.Timestamp("2020-02-20")        # бал лише після дірки довшої за 14 днів
