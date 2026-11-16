"""
ui_overview.py
Два зведені графіки головної сторінки (app.py):

1) «У скільки разів більше, ніж у грудні 2023» - одна логарифмічна вісь разів:
   - автономність моделі-лідера: METR T50 (autonomy_t50_frontier); після останнього виміру -
     оцінка за Epoch ECI (зв'язок log10(1 + T50 хв) = a + b * ECI, підібраний з 2024-01), пунктир;
   - фахівці ШІ: частка вакансій зі згадкою ШІ, Indeed AI Tracker, усі країни трекера одною лінією -
     середнє геометричне зростання країн, рівна вага (indeed_ai_share, metrics/people.py);
   - гроші: квартальні капвитрати Amazon, Alphabet, Meta, Microsoft (SEC EDGAR), простір під
     лінією залито за джерелами: власний заробіток / борг / продаж акцій (частки надходжень
     кварталу, застосовані до капвитрат - компанії не розкривають, з чого оплачено будівництво).
2) «На що спрямовані дослідження ШІ: на зростання автономності чи на людський нагляд» -
   щоквартально два стовпчики (arxiv_group_autonomy, arxiv_group_oversight); усередині - напрями
   (arxiv_share_*), поділені пропорційно, бо одна стаття може стосуватися кількох напрямів.
   Назви - з Регламенту ЄС про ШІ 2024/1689 (ст. 3(1), 14, 15).

Лише читання з бази; розрахунки рядів - у збирачах.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from collectors.arxiv_counts import DIRECTIONS, GROUPS
from metrics.people import people_growth

BASE_MONTH = pd.Timestamp("2023-12-01")
BASE_QUARTER_END = pd.Timestamp("2023-12-31")
HYPERSCALERS = ("AMZN", "GOOGL", "META", "MSFT")
FIT_FROM = pd.Timestamp("2024-01-01")

C_AUTONOMY = "#7F77DD"
C_PEOPLE = "#1D9E75"
C_MONEY = "#854F0B"
C_OWN, C_DEBT, C_EQUITY = "#B4B2A9", "#EF9F27", "#D85A30"

DIR_COLORS = {
    "agents": "#993C1D", "self_improvement": "#D4537E", "robots": "#EF9F27", "reasoning": "#B4B2A9",
    "ai_science": "#7F77DD",
    # нагляд: сині й бірюзові, що різняться світлотою, щоб не зливатися
    "oversight": "#1D9E75", "understanding": "#185FA5", "robustness": "#0C447C", "undesired": "#85B7EB",
    "risk": "#B5D4F4", "stop_resistance": "#04342C",
}


def _t(is_en: bool, en: str, ua: str) -> str:
    return en if is_en else ua


def show_chart(fig, **kwargs) -> None:
    """Графік без наближення пальцем: на телефоні провід по графіку інакше масштабує його."""
    fig.update_layout(dragmode=False)
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    config = {"displayModeBar": False, "scrollZoom": False, **kwargs.pop("config", {})}
    kwargs.setdefault("use_container_width", True)
    kwargs.setdefault("theme", None)
    st.plotly_chart(fig, config=config, **kwargs)


def _fetch(sb, metric_id: str, region: str | None = "GLOBAL", cols: str = "period_start,value") -> pd.DataFrame:
    rows, off = [], 0
    while True:
        q = sb.table("fct_metric_values").select(cols).eq("metric_id", metric_id)
        if region:
            q = q.eq("region", region)
        page = q.order("period_start").range(off, off + 999).execute().data or []
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    df = pd.DataFrame(rows)
    if not df.empty:
        df["period_start"] = pd.to_datetime(df["period_start"])
        for c in ("value", "numerator", "denominator"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------- дані головного графіка

def load_people_monthly(sb) -> pd.DataFrame:
    """Місячна частка вакансій зі згадкою ШІ за країнами: region, month, value.
    Основне джерело - представлення sql/028 (усі країни трекера); без нього - лише США, як раніше."""
    try:
        rows, off = [], 0
        while True:
            page = (sb.table("v_indeed_ai_share_monthly").select("region,month,value")
                    .gte("month", (BASE_MONTH - pd.DateOffset(months=1)).strftime("%Y-%m-%d"))
                    .order("region").order("month").range(off, off + 999).execute().data or [])
            rows += page
            if len(page) < 1000:
                break
            off += 1000
        df = pd.DataFrame(rows)
        if not df.empty:
            df["month"] = pd.to_datetime(df["month"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            return df
    except Exception:
        pass
    us = _fetch(sb, "indeed_ai_share", "US")
    if us.empty:
        return pd.DataFrame(columns=["region", "month", "value"])
    us = us.assign(month=us["period_start"].dt.to_period("M").dt.to_timestamp())
    return us.groupby("month", as_index=False)["value"].mean().assign(region="US")


CN_LAB_NAMES = {"deepseek": "DeepSeek", "moonshot": "Moonshot", "minimax": "MiniMax", "zhipu": "Zhipu"}   # як у collectors/cn_lab_jobs.py


def load_cn_labs(sb) -> dict:
    """Останній знімок відкритих вакансій китайських лабораторій (collectors/cn_lab_jobs.py):
    {"day": дата, "labs": {назва: кількість}}; лише лабораторії з даними за останню дату."""
    try:
        rows = (sb.table("fct_metric_values").select("metric_id,period_start,value")
                .like("metric_id", "cn_lab_jobs_%").eq("region", "CN")
                .order("period_start", desc=True).limit(30).execute().data or [])
    except Exception:
        rows = []
    if not rows:
        return {"day": None, "labs": {}}
    day = rows[0]["period_start"]
    labs = {}
    for r in rows:
        if r["period_start"] == day and r.get("value") is not None:
            key = r["metric_id"].removeprefix("cn_lab_jobs_")
            labs[CN_LAB_NAMES.get(key, key.title())] = int(float(r["value"]))
    return {"day": pd.Timestamp(day), "labs": labs}


@st.cache_data(ttl=600, show_spinner=False)
def load_growth(_sb) -> tuple[dict | None, str | None]:
    try:
        t50 = _fetch(_sb, "autonomy_t50_frontier")
        eci = pd.DataFrame(_sb.table("fct_capability_index").select("release_date,eci").execute().data)
        ai = load_people_monthly(_sb)
        fin = pd.DataFrame(_sb.table("fct_lab_financials")
                           .select("ticker,metric,period_end,value,filed_date")
                           .eq("period_type", "quarter").in_("ticker", list(HYPERSCALERS))
                           .in_("metric", ["capex", "ocf", "debt_issued", "debt_repaid", "equity_issued"])
                           .gte("period_end", "2023-10-01").execute().data)
        return {"t50": t50, "eci": eci, "ai": ai, "fin": fin, "cn_labs": load_cn_labs(_sb)}, None
    except Exception as ex:
        return None, str(ex)[:300]


def autonomy_series(t50: pd.DataFrame, eci: pd.DataFrame) -> dict:
    """Помісячні години T50: виміряні й оцінка за ECI після останнього виміру."""
    t = t50.assign(m=t50["period_start"].dt.to_period("M").dt.to_timestamp())[["m", "value"]] \
           .groupby("m")["value"].max()
    eci = eci.dropna().copy()
    eci["release_date"] = pd.to_datetime(eci["release_date"])
    eci["eci"] = pd.to_numeric(eci["eci"], errors="coerce")
    months = pd.date_range(BASE_MONTH, pd.Timestamp.today().normalize().replace(day=1), freq="MS")
    frontier = pd.Series({m: eci.loc[eci["release_date"] < m + pd.offsets.MonthBegin(1), "eci"].max()
                          for m in pd.date_range("2023-01-01", months[-1], freq="MS")})
    fit = pd.DataFrame({"y": np.log10(1 + 60 * t), "x": frontier}).dropna()
    fit = fit[fit.index >= FIT_FROM]
    b, a = np.polyfit(fit["x"], fit["y"], 1)
    resid = fit["y"] - (a + b * fit["x"])
    se = float(np.sqrt((resid ** 2).sum() / max(1, len(fit) - 2)))
    r2 = float(1 - (resid ** 2).sum() / ((fit["y"] - fit["y"].mean()) ** 2).sum())
    last_measured = t.index.max()
    hours = lambda lg: (10 ** lg - 1) / 60
    est = {m: (hours(a + b * frontier[m]), hours(a + b * frontier[m] - 2 * se), hours(a + b * frontier[m] + 2 * se))
           for m in months if m > last_measured and not math.isnan(frontier.get(m, float("nan")))}
    return {"measured": t[t.index >= BASE_MONTH], "estimate": est, "base": float(t.get(BASE_MONTH, np.nan)),
            "a": a, "b": b, "se": se, "r2": r2, "n": len(fit), "last_measured": last_measured}


def money_quarters(fin: pd.DataFrame) -> pd.DataFrame:
    """Квартали з даними всіх чотирьох компаній: капвитрати і частки джерел надходжень."""
    f = fin.copy()
    f["period_end"] = pd.to_datetime(f["period_end"])
    f["value"] = pd.to_numeric(f["value"], errors="coerce")
    f = f.sort_values("filed_date").drop_duplicates(["ticker", "metric", "period_end"], keep="last")
    p = f.pivot_table(index=["period_end", "ticker"], columns="metric", values="value", aggfunc="last").fillna(0)
    p = p.reset_index()
    capex_n = p[p.get("capex", 0) > 0].groupby("period_end")["ticker"].nunique()
    full = capex_n[capex_n == len(HYPERSCALERS)].index
    p = p[p["period_end"].isin(full)]
    g = p.groupby("period_end").sum(numeric_only=True)
    for c in ("ocf", "debt_issued", "debt_repaid", "equity_issued"):
        if c not in g.columns:
            g[c] = 0.0
    g["debt_net"] = (g["debt_issued"] - g["debt_repaid"]).clip(lower=0)
    inflow = g["ocf"] + g["debt_net"] + g["equity_issued"]
    g["s_own"], g["s_debt"], g["s_eq"] = g["ocf"] / inflow, g["debt_net"] / inflow, g["equity_issued"] / inflow
    return g[g.index >= BASE_QUARTER_END]


def render_growth(sb, is_en: bool) -> None:
    st.markdown("<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin:6px 0 2px;'>"
                + _t(is_en, "How fast it grows: autonomy, AI specialists and money",
                     "Як швидко зростає: автономність, фахівці ШІ і гроші")
                + "</div>", unsafe_allow_html=True)
    st.caption(_t(is_en, "Times more than in December 2023 · one scale for all three lines · hover or tap for details",
                  "У скільки разів більше, ніж у грудні 2023 · одна шкала для трьох ліній · наведіть або торкніться"))
    data, err = load_growth(sb)
    if err or not data:
        st.caption(f"⚠️ {err}")
        return
    try:
        aut = autonomy_series(data["t50"], data["eci"])
        money = money_quarters(data["fin"])
        people = people_growth(data["ai"], BASE_MONTH)
    except Exception as ex:
        st.caption(f"⚠️ {type(ex).__name__}: {str(ex)[:200]}")
        return

    fig = go.Figure()
    # --- гроші: заливка за джерелами від ×1 до лінії капвитрат
    if not money.empty and BASE_QUARTER_END in money.index:
        base = money.loc[BASE_QUARTER_END, "capex"]
        mult = money["capex"] / base
        own = (mult * money["s_own"]).clip(lower=1)
        own_debt = (mult * (money["s_own"] + money["s_debt"])).clip(lower=1)
        x = money.index
        txt = [_t(is_en,
                  f"Q{d.quarter} {d.year}: ${c / 1e9:.0f}bn capex · own {so:.0%} · debt {sd:.0%} · equity {se_:.0%}",
                  f"{d.quarter} кв. {d.year}: ${c / 1e9:.0f} млрд · заробіток {so:.0%} · борг {sd:.0%} · акції {se_:.0%}")
               for d, c, so, sd, se_ in zip(x, money["capex"], money["s_own"], money["s_debt"], money["s_eq"])]
        fig.add_trace(go.Scatter(x=x, y=[1] * len(x), mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False))
        for y, col, name in ((own, C_OWN, _t(is_en, "own earnings", "власний заробіток")),
                             (own_debt, C_DEBT, _t(is_en, "debt", "борг")),
                             (mult, C_EQUITY, _t(is_en, "share sales", "продаж акцій"))):
            fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(width=0), fill="tonexty", fillcolor=col,
                                     opacity=0.85, name=name, hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=x, y=mult, mode="lines+markers", line=dict(color=C_MONEY, width=2),
                                 marker=dict(size=5), name=_t(is_en, "Money", "Гроші"),
                                 text=txt, hovertemplate="%{text}<br>×%{y:.1f}<extra></extra>"))
    # --- фахівці ШІ
    a_m = people["mult"]
    if not a_m.empty:
        fig.add_trace(go.Scatter(
            x=a_m.index, y=a_m, mode="lines", line=dict(color=C_PEOPLE, width=2.5),
            name=_t(is_en, "AI specialists", "Фахівці ШІ"),
            customdata=np.stack([people["n"].reindex(a_m.index), people["low"].reindex(a_m.index),
                                 people["high"].reindex(a_m.index)], axis=1),
            hovertemplate=_t(
                is_en,
                "%{x|%b %Y}: ×%{y:.1f} — mean of %{customdata[0]:.0f} countries<br>"
                "from ×%{customdata[1]:.1f} to ×%{customdata[2]:.1f} across countries<extra></extra>",
                "%{x|%m.%Y}: ×%{y:.1f} — середнє %{customdata[0]:.0f} країн<br>"
                "від ×%{customdata[1]:.1f} до ×%{customdata[2]:.1f} між країнами<extra></extra>")))
    # --- автономність
    b0 = aut["base"]
    if b0 and not math.isnan(b0):
        meas = aut["measured"]
        fig.add_trace(go.Scatter(
            x=meas.index, y=meas / b0, mode="lines+markers", line=dict(color=C_AUTONOMY, width=3), marker=dict(size=5),
            name=_t(is_en, "Autonomy", "Автономність"),
            text=[f"{h:.1f}" for h in meas],
            hovertemplate=_t(is_en, "%{x|%b %Y}: %{text} h task (METR T50)<br>×%{y:.0f}<extra></extra>",
                             "%{x|%m.%Y}: завдання на %{text} год (METR T50)<br>×%{y:.0f}<extra></extra>")))
        if aut["estimate"]:
            ex_ = [aut["last_measured"]] + sorted(aut["estimate"])
            mid = [meas.iloc[-1] / b0] + [aut["estimate"][m][0] / b0 for m in ex_[1:]]
            lo = [meas.iloc[-1] / b0] + [aut["estimate"][m][1] / b0 for m in ex_[1:]]
            hi = [meas.iloc[-1] / b0] + [aut["estimate"][m][2] / b0 for m in ex_[1:]]
            fig.add_trace(go.Scatter(x=ex_ + ex_[::-1], y=hi + lo[::-1], mode="lines", fill="toself",
                                     fillcolor="rgba(127,119,221,0.15)", line=dict(width=0),
                                     hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(
                x=ex_, y=mid, mode="lines", line=dict(color=C_AUTONOMY, width=3, dash="dash"),
                name=_t(is_en, "estimate", "оцінка"),
                text=[f"{v * b0:.0f}" for v in mid],
                hovertemplate=_t(is_en, "%{x|%b %Y}: ≈ %{text} h (estimate)<br>×%{y:.0f}<extra></extra>",
                                 "%{x|%m.%Y}: ≈ %{text} год (оцінка)<br>×%{y:.0f}<extra></extra>")))
    x_end = pd.Timestamp.today().normalize() + pd.DateOffset(months=1)
    fig.update_layout(height=400, paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", hovermode="closest",
                      margin=dict(l=44, r=8, t=8, b=8),
                      font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=10),
                                  itemwidth=30, tracegroupgap=0, bgcolor="rgba(255,255,255,0)"),
                      yaxis=dict(type="log", gridcolor="#f1f5f9", automargin=False, range=[-0.03, 3.1],
                                 tickvals=[1, 2, 5, 10, 20, 50, 100, 200, 500, 1000],
                                 ticktext=["×1", "×2", "×5", "×10", "×20", "×50", "×100", "×200", "×500", "×1000"]),
                      xaxis=dict(gridcolor="#f8fafc", range=[BASE_MONTH - pd.DateOffset(days=20), x_end],
                                 dtick="M12", tickformat="%Y"))
    show_chart(fig)
    sq = "display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px;"
    st.markdown("<div style='font-size:0.75rem;color:#475569;margin:-6px 0 8px;'>"
                + _t(is_en, "Money by source:", "Гроші за джерелами:")
                + f"<span style='{sq}background:{C_OWN}'></span>" + _t(is_en, "own earnings", "власний заробіток")
                + f"<span style='{sq}background:{C_DEBT}'></span>" + _t(is_en, "debt", "борг")
                + f"<span style='{sq}background:{C_EQUITY}'></span>" + _t(is_en, "share sales", "продаж акцій")
                + "</div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(_t(is_en,
                       f"**Leader autonomy** — length of a task the model completes alone (METR T50). Base: "
                       f"{b0 * 60:.0f} min. After {aut['last_measured']:%b %Y} — estimate from Epoch ECI: "
                       f"log10(1 + T50 min) = {aut['a']:.2f} + {aut['b']:.4f} × ECI (R² {aut['r2']:.2f}, {aut['n']} months), "
                       f"band ±2σ. Sources: METR via Epoch AI, Epoch ECI (CC BY 4.0).",
                       f"**Автономність лідера** — довжина завдання, яке модель виконує сама (METR T50). База: "
                       f"{b0 * 60:.0f} хв. Після {aut['last_measured']:%m.%Y} — оцінка за Epoch ECI: "
                       f"log10(1 + T50 хв) = {aut['a']:.2f} + {aut['b']:.4f} × ECI (R² {aut['r2']:.2f}, {aut['n']} міс.), "
                       f"смуга ±2σ. Джерела: METR через Epoch AI, Epoch ECI (CC BY 4.0)."))
    with c2:
        by_country = ", ".join(f"{r} ×{v:.1f}" for r, v in sorted(people["latest"].items(), key=lambda kv: -kv[1]))
        n_reg = len(people["regions"])
        cn = data.get("cn_labs") or {"day": None, "labs": {}}
        if cn["labs"]:
            cn_list = ", ".join(f"{k} {v}" for k, v in sorted(cn["labs"].items(), key=lambda kv: -kv[1]))
            cn_en = (f" China is not in the tracker (Indeed does not operate there). Shown separately, not in the line: "
                     f"{sum(cn['labs'].values())} open postings on the career pages of leading Chinese labs "
                     f"({cn_list}; {cn['day']:%d.%m.%Y}) — a count of the companies' own postings, not a market share.")
            cn_ua = (f" Китаю в трекері немає (Indeed там не працює). Окремо, поза лінією: на сторінках найму "
                     f"китайських лабораторій-лідерів відкрито {sum(cn['labs'].values())} вакансій "
                     f"({cn_list}; {cn['day']:%d.%m.%Y}) — це кількість оголошень самих компаній, а не частка ринку.")
        else:
            cn_en = " China is not covered: Indeed does not operate there."
            cn_ua = " Китаю немає: Indeed там не працює."
        st.markdown(_t(is_en,
                       f"**AI specialists** — share of job postings mentioning AI terms; one line for all "
                       f"{n_reg} countries of the tracker: geometric mean of each country's growth, equal weight "
                       f"(Indeed publishes shares, not posting counts, so countries cannot be summed or weighted "
                       f"by size). Latest month: {by_country}.{cn_en} "
                       f"Counts keywords, not job titles. Source: Indeed Hiring Lab AI Tracker (CC BY 4.0).",
                       f"**Фахівці ШІ** — частка вакансій, що згадують терміни ШІ; одна лінія за всіма країнами "
                       f"трекера ({n_reg}): середнє геометричне зростання країн, рівна вага (Indeed публікує частки, "
                       f"а не кількість вакансій, тож скласти країни чи зважити їх за розміром неможливо). "
                       f"Останній місяць: {by_country}.{cn_ua} "
                       f"Рахує ключові слова, а не посади. Джерело: Indeed Hiring Lab AI Tracker (CC BY 4.0)."))
    with c3:
        st.markdown(_t(is_en,
                       "**Money** — quarterly capex of Amazon, Alphabet, Meta, Microsoft (whole companies, not AI only). "
                       "Fill: share of the quarter's inflows from own operating cash flow, net debt and share sales, "
                       "applied to capex. OpenAI, Anthropic, xAI do not file with the SEC. Source: SEC EDGAR.",
                       "**Гроші** — квартальні капвитрати Amazon, Alphabet, Meta, Microsoft (уся компанія, не лише ШІ). "
                       "Заливка: частки надходжень кварталу від власного заробітку, чистого боргу й продажу акцій, "
                       "застосовані до капвитрат. OpenAI, Anthropic, xAI не звітують до SEC. Джерело: SEC EDGAR."))


# ---------------------------------------------------------------- дослідження: автономність проти нагляду

@st.cache_data(ttl=600, show_spinner=False)
def load_research(_sb) -> tuple[pd.DataFrame | None, str | None, str | None]:
    """Помісячні ряди ArXiv поточної версії методу (останній запис arxiv_papers_total)."""
    try:
        last = (_sb.table("fct_metric_values").select("method_version").eq("metric_id", "arxiv_papers_total")
                .order("computed_at", desc=True).limit(1).execute().data)
        if not last:
            return pd.DataFrame(), None, None
        ver = last[0]["method_version"]
        ids = [f"arxiv_share_{k}" for k in DIRECTIONS] + [f"arxiv_group_{g}" for g in GROUPS]
        rows, off = [], 0
        while True:
            page = (_sb.table("fct_metric_values")
                    .select("metric_id,period_start,value,numerator,denominator,is_estimate")
                    .in_("metric_id", ids).eq("method_version", ver)
                    .order("period_start").range(off, off + 999).execute().data or [])
            rows += page
            if len(page) < 1000:
                break
            off += 1000
        df = pd.DataFrame(rows)
        if not df.empty:
            df["period_start"] = pd.to_datetime(df["period_start"])
            for c in ("value", "numerator", "denominator"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
        return df, None, ver
    except Exception as ex:
        return None, str(ex)[:300], None


def research_quarters(df: pd.DataFrame, is_en: bool) -> tuple[pd.DataFrame, list[str]]:
    """Квартальні частки (% статей ШІ) за показниками та підписи кварталів від старого до нового.
    Неповний квартал (менше трьох місяців або оцінка) позначено зірочкою."""
    df = df.copy()
    df["q"] = df["period_start"].dt.to_period("Q")
    agg = df.groupby(["q", "metric_id"])[["numerator", "denominator"]].sum()
    agg["pct"] = 100 * agg["numerator"] / agg["denominator"]
    pct = agg["pct"].unstack("metric_id")
    group_cols = [c for c in pct.columns if c.startswith("arxiv_group_")]
    pct = pct.dropna(subset=group_cols, how="all") if group_cols else pct.iloc[0:0]
    anchor = df[df["metric_id"].str.startswith("arxiv_group_")]
    months_in_q = anchor.groupby("q")["period_start"].nunique()
    partial = anchor.groupby("q")["is_estimate"].any()
    labels = [f"{p.quarter} {_t(is_en, 'Q', 'кв')} {p.year}" + ("*" if partial.get(p) or months_in_q.get(p, 3) < 3 else "")
              for p in pct.index]
    return pct, labels


def _wrap(text: str) -> str:
    """Довгий підпис стовпчика - у два рядки, перенос біля середини."""
    words = text.split()
    if len(words) < 3:
        return text
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]) + "<br>" + " ".join(words[best:])


def render_research(sb, is_en: bool) -> None:
    st.markdown("<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin:6px 0 2px;'>"
                + _t(is_en, "What AI research is aimed at: growing autonomy or human oversight",
                     "На що спрямовані дослідження ШІ: на зростання автономності чи на людський нагляд")
                + "</div>", unsafe_allow_html=True)
    df, err, ver = load_research(sb)
    if err:
        st.caption(f"⚠️ {err}")
        return
    if df is None or df.empty or not df["metric_id"].str.startswith("arxiv_group_").any():
        st.info(_t(is_en, "History is being collected (about 10 months per daily run).",
                   "Історія збирається (близько 10 місяців за щоденний запуск)."))
        return

    pct, labels = research_quarters(df, is_en)
    if pct.empty:
        st.info(_t(is_en, "History is being collected (about 10 months per daily run).",
                   "Історія збирається (близько 10 місяців за щоденний запуск)."))
        return

    # На графіку - один квартал (останній); попередні - у випадаючому меню. На телефоні
    # два широкі стовпчики з підписами читаються, а ряд із десятка кварталів - ні.
    options = labels[::-1]
    c_period, c_share = st.columns([1, 1])
    with c_period:
        chosen = st.selectbox(_t(is_en, "Quarter", "Квартал"), options, index=0, key="research_period")
    with c_share:
        as_share = st.toggle(_t(is_en, "Stretch both bars to 100 %", "Розтягнути обидва стовпчики до 100 %"),
                             value=False, key="research_share")
    row = pct.iloc[labels.index(chosen)]

    fig = go.Figure()
    shares: dict[str, float] = {}      # напрям -> % свого стовпчика (для легенди під графіком)
    top = 0.0
    for g, (ua, en) in GROUPS.items():
        members = [k for k, v in DIRECTIONS.items() if v[3] == g and f"arxiv_share_{k}" in pct.columns]
        height = row.get(f"arxiv_group_{g}")
        if height is None or pd.isna(height) or not members:
            continue
        height = float(height)
        raw = row[[f"arxiv_share_{k}" for k in members]].fillna(0).astype(float)
        total = float(raw.sum())
        scale = 100.0 if as_share else height
        top = max(top, scale)
        x_label = _wrap(_t(is_en, en, ua))
        for k in members:
            part = float(raw[f"arxiv_share_{k}"]) / total if total > 0 else 0.0
            shares[k] = part * 100
            d_ua, d_en = DIRECTIONS[k][0], DIRECTIONS[k][1]
            fig.add_trace(go.Bar(
                x=[x_label], y=[part * scale], name=_t(is_en, d_en, d_ua),
                marker_color=DIR_COLORS.get(k, "#94a3b8"), marker_line=dict(color="#ffffff", width=0.5),
                text=[f"{part * 100:.0f} %"], textposition="inside", insidetextanchor="middle",
                textfont=dict(size=11), showlegend=False,
                customdata=[[float(raw[f"arxiv_share_{k}"]), part * 100, height]],
                hovertemplate=(f"<b>{_t(is_en, d_en, d_ua)}</b><br>"
                               + _t(is_en, "%{customdata[0]:.2f}% of AI papers · %{customdata[1]:.0f}% of the bar",
                                    "%{customdata[0]:.2f} % статей ШІ · %{customdata[1]:.0f} % стовпчика")
                               + f"<br>{_t(is_en, en, ua)}: %{{customdata[2]:.1f}} %<extra></extra>")))
        fig.add_annotation(x=x_label, y=scale, yshift=12, showarrow=False,
                           text=f"<b>{height:.1f} %</b> " + _t(is_en, "of AI papers", "статей ШІ"),
                           font=dict(size=12, color="#0f172a"))
    fig.update_layout(barmode="stack", bargap=0.3, height=400,
                      paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", hovermode="closest",
                      margin=dict(l=40, r=8, t=28, b=48),
                      uniformtext=dict(minsize=9, mode="hide"),
                      xaxis=dict(type="category", tickfont=dict(size=11), automargin=False),
                      font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
                      showlegend=False,
                      yaxis=dict(gridcolor="#f1f5f9", ticksuffix=" %", automargin=False,
                                 range=[0, top * 1.12 if top > 0 else 1]))
    show_chart(fig)
    sq = "display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 3px 0 8px;vertical-align:-1px;"
    for g, (ua, en) in GROUPS.items():
        items = "".join(f"<span style='white-space:nowrap'><span style='{sq}background:{DIR_COLORS.get(k, '#94a3b8')}'></span>"
                        f"{_t(is_en, v[1], v[0])} <b>{shares[k]:.0f} %</b></span> "
                        for k, v in DIRECTIONS.items() if v[3] == g and k in shares)
        st.markdown(f"<div style='font-size:0.72rem;color:#475569;line-height:1.7;margin:0 0 4px;'>"
                    f"<b>{_t(is_en, en, ua)}:</b>{items}</div>", unsafe_allow_html=True)
    st.caption(_t(
        is_en,
        "One quarter is shown; earlier quarters are in the menu above the chart. Left bar — growth of AI autonomy "
        "(features from the AI system definition, Art. 3(1) of Regulation (EU) 2024/1689); right bar — human oversight "
        "and robustness (Art. 14, 15; formally for high-risk systems, used here as names of research directions). "
        "The number above a bar is the share of AI papers on ArXiv in that quarter (each paper counted once); the "
        "numbers inside and in the list below are shares of the bar (directions are split proportionally). "
        "* — quarter not complete yet. Source: arXiv API (cs.AI, cs.LG, cs.CL, cs.RO, cs.MA).",
        "Показано один квартал; попередні — у меню над графіком. Лівий стовпчик — зростання автономності ШІ "
        "(ознаки з визначення системи ШІ, ст. 3(1) Регламенту ЄС 2024/1689); правий — людський нагляд і надійність "
        "(ст. 14, 15; формально стосуються систем високого ризику, тут — назви напрямів досліджень). "
        "Число над стовпчиком — частка статей ШІ на ArXiv за квартал (кожна стаття рахується один раз); числа "
        "всередині та в переліку під графіком — частки стовпчика (напрями поділено пропорційно). "
        "* — квартал ще не завершено. Джерело: arXiv API (cs.AI, cs.LG, cs.CL, cs.RO, cs.MA)."))
