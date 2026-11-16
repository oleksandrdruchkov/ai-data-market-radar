"""Лінія «Фахівці ШІ»: середнє геометричне зростання країн відносно базового місяця."""

import pandas as pd

from metrics.people import people_growth

BASE = pd.Timestamp("2023-12-01")


def frame(rows):
    return pd.DataFrame([{"region": r, "month": pd.Timestamp(m), "value": v} for r, m, v in rows])


def test_geometric_mean_equal_weight():
    g = people_growth(frame([
        ("US", "2023-11-01", 1.0), ("US", "2023-12-01", 2.0), ("US", "2024-01-01", 4.0),    # x2
        ("DE", "2023-12-01", 1.0), ("DE", "2024-01-01", 8.0),                               # x8
    ]), BASE)
    assert list(g["mult"].index) == [BASE, pd.Timestamp("2024-01-01")]      # до бази - не показується
    assert abs(g["mult"].iloc[0] - 1) < 1e-12
    assert abs(g["mult"].iloc[1] - 4) < 1e-12                               # sqrt(2 * 8)
    assert g["low"].iloc[1] == 2 and g["high"].iloc[1] == 8 and g["n"].iloc[1] == 2
    assert g["regions"] == ["DE", "US"] and g["latest"] == {"DE": 8.0, "US": 2.0}


def test_country_without_base_is_left_out_and_gaps_do_not_break():
    g = people_growth(frame([
        ("US", "2023-12-01", 2.0), ("US", "2024-01-01", 3.0), ("US", "2024-02-01", 4.0),
        ("IN", "2024-01-01", 5.0), ("IN", "2024-02-01", 50.0),              # немає бази - не враховується
        ("GB", "2023-12-01", 1.0), ("GB", "2024-01-01", 1.5),               # лютого ще немає
    ]), BASE)
    assert g["regions"] == ["GB", "US"]
    assert abs(g["mult"].iloc[1] - 1.5) < 1e-12 and g["n"].iloc[1] == 2
    assert abs(g["mult"].iloc[2] - 2.0) < 1e-12 and g["n"].iloc[2] == 1     # лише країни з даними за місяць


def test_empty_or_no_base():
    assert people_growth(frame([("US", "2024-01-01", 2.0)]), BASE)["mult"].empty
    assert people_growth(pd.DataFrame(), BASE)["regions"] == []


def labs(rows):
    return pd.DataFrame([{"lab": lab, "day": pd.Timestamp(d), "value": v} for lab, d, v in rows])


def test_cn_labs_bars_daily_and_incomplete_days():
    from metrics.people import cn_labs_bars
    wide, mode = cn_labs_bars(labs([
        ("DeepSeek", "2026-11-17", 36), ("Moonshot", "2026-11-17", 106),
        ("DeepSeek", "2026-11-18", 37),                                   # Moonshot не відповів - дня немає
        ("DeepSeek", "2026-11-19", 38), ("Moonshot", "2026-11-19", 104),
    ]))
    assert mode == "day" and list(wide.index.strftime("%m-%d")) == ["11-17", "11-19"]
    assert wide.loc["2026-11-19", "Moonshot"] == 104
    assert cn_labs_bars(pd.DataFrame())[0].empty


def test_cn_labs_bars_weekly_after_two_weeks():
    from metrics.people import cn_labs_bars
    days = pd.date_range("2026-11-16", periods=30)                        # понеділок
    wide, mode = cn_labs_bars(labs([("DeepSeek", d, 30 + i) for i, d in enumerate(days)]))
    assert mode == "week" and len(wide) == 5                              # 4 повні тижні + початий
    assert wide.index[0] == pd.Timestamp("2026-11-22") and wide.iloc[0, 0] == 36   # останній знімок тижня
    assert wide.index[-1] == days[-1]
