import os
import re
import json
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client

st.set_page_config(
    page_title="Market & AI Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    background-color: #f8fafc !important;
    color: #0f172a !important;
}

.block-container {
    padding-top: 0.4rem !important;
    padding-bottom: 1.5rem !important;
    padding-left: 0.6rem !important;
    padding-right: 0.6rem !important;
}

header[data-testid="stHeader"] {
    display: none !important;
}

.market-status-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 10px;
    margin-bottom: 8px;
}

.market-indicator {
    flex: 1 1 calc(50% - 6px);
    display: flex;
    flex-direction: column;
}

.indicator-title {
    font-size: 0.65rem;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    line-height: 1.1;
}

.indicator-val {
    font-size: 0.95rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 4px;
}

.badge-green {
    background: #dcfce7;
    color: #15803d;
    font-size: 0.65rem;
    padding: 1px 5px;
    border-radius: 4px;
    font-weight: 700;
}

.badge-blue {
    background: #e0f2fe;
    color: #0284c7;
    font-size: 0.65rem;
    padding: 1px 5px;
    border-radius: 4px;
    font-weight: 700;
}

.future-role-card {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.future-role-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
}

.future-role-title {
    font-size: 0.9rem;
    font-weight: 800;
    color: #0f172a;
}

.future-role-badge {
    background: #ede9fe;
    color: #6d28d9;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
}

.lead-time-wrap {
    margin: 4px 0 8px 0;
}

.lead-time-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.68rem;
    color: #64748b;
    font-weight: 600;
    margin-bottom: 3px;
}

.lead-time-bg {
    width: 100%;
    height: 5px;
    background: #e2e8f0;
    border-radius: 3px;
    overflow: hidden;
}

.lead-time-bar {
    height: 100%;
    background: linear-gradient(90deg, #0284c7 0%, #6366f1 100%);
    border-radius: 3px;
}

.future-skill-tag {
    display: inline-block;
    background: #e0f2fe;
    color: #0284c7;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    margin-bottom: 5px;
}

.future-role-desc {
    font-size: 0.78rem;
    color: #475569;
    line-height: 1.35;
}

div[data-testid="stPlotlyChart"] {
    background: #ffffff !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #cbd5e1 !important;
}
</style>
""", unsafe_allow_html=True)

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co"))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_KEY in Secrets.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

@st.cache_data(ttl=120)
def load_data():
    try:
        res_skills = supabase.table("v_skill_demand_stats").select("*").execute()
        df_s = pd.DataFrame(res_skills.data)
    except Exception:
        df_s = pd.DataFrame()

    try:
        res_arxiv = supabase.table("fct_arxiv_signals").select("*").order("published_date", desc=True).limit(6).execute()
        df_ar = pd.DataFrame(res_arxiv.data)
    except Exception:
        df_ar = pd.DataFrame()

    try:
        res_health = supabase.table("v_pipeline_health").select("*").limit(5).execute()
        df_h = pd.DataFrame(res_health.data)
    except Exception:
        df_h = pd.DataFrame()

    return df_s, df_ar, df_h

@st.cache_data(ttl=60)
def load_horizon_data():
    """Виміри горизонту автономності моделей з усіх джерел (METR, UK AISI, Redwood ...).
    Повертає (DataFrame, текст помилки або None), щоб збій читання не маскувався під порожню таблицю."""
    try:
        res = supabase.table("fct_autonomy_horizons").select("*").eq("is_synthetic", False).execute()
        return pd.DataFrame(res.data), None
    except Exception as e:
        return pd.DataFrame(), str(e)[:300]

@st.cache_data(ttl=120)
def load_circle_data():
    try:
        res = supabase.table("fct_action_circle_monthly")\
            .select("*")\
            .order("period", desc=True)\
            .execute()
        df = pd.DataFrame(res.data)
        if df.empty:
            return pd.DataFrame()

        if "source_type" in df.columns:
            df["priority"] = df["source_type"].apply(
                lambda x: 2 if str(x).strip() == "Frontier System Card Audit" else 1
            )
            df = df.sort_values(by=["period", "priority"], ascending=[False, False])
            df = df.drop_duplicates(subset=["period"], keep="first").reset_index(drop=True)
        else:
            df["source_type"] = "live_telemetry"
            df["source_reference"] = "AI Incident Database & Inspect Evals"

        return df
    except Exception:
        return pd.DataFrame()

df_skills_base, df_arxiv, df_health = load_data()
df_hor, hor_error = load_horizon_data()
df_circ_raw = load_circle_data()

# ==========================================
# ШАПКА: СЕЛЕКТОР МОВИ ТА РЕГІОНІВ
# ==========================================
col_head, col_lang, col_reg = st.columns([1.1, 0.55, 1.1])
with col_head:
    st.markdown("<div style='font-weight:800; font-size:1.05rem; color:#0f172a; padding-top:4px;'>📡 Market Radar</div>", unsafe_allow_html=True)

with col_lang:
    selected_lang = st.selectbox(
        "Language",
        options=["UA", "EN"],
        index=0,
        label_visibility="collapsed"
    )

is_en = (selected_lang == "EN")

L = {
    "dominant": "DOMINANT CORE" if is_en else "ДОМІНУЮЧЕ ЯДРО",
    "velocity": "VELOCITY BREAKOUT" if is_en else "ПРОРИВ ШВИДКОСТІ",
    "indexed": "INDEXED SIGNALS" if is_en else "ПРОІНДЕКСОВАНО",
    "status": "FEED STATUS" if is_en else "СТАТУС ФІДУ",
    "live": "Live" if is_en else "Наживо",
    "tab_demand": "🔥 Demand Velocity" if is_en else "🔥 Попит на ринку",
    "tab_future": "🔮 Future Roles (3–6 Mo.)" if is_en else "🔮 Майбутні ролі (3–6 міс.)",
    "empty_skills": "No matching skills found for" if is_en else "Не знайдено навичок для",
    "empty_arxiv": "ArXiv research pipeline is syncing." if is_en else "Сигнали ArXiv синхронізуються.",
    "future_caption": "⚡ **Leading R&D Indicators (ArXiv)** — Predicted tech stack readiness and commercial hiring lead-time." if is_en else "⚡ **Leading R&D Indicators (ArXiv)** — Прогноз появи комерційних вакансій та стадії готовності технологій.",
    "market_lead": "⏱️ Market Lead:" if is_en else "⏱️ Публічний ринок:",
    "stack_readiness": "Stack Readiness:" if is_en else "Готовність стеку:",
    "stage_high": "🔥 High Momentum (Commercial Hiring)" if is_en else "🔥 High Momentum (Вихід у комерційні вакансії)",
    "stage_frontier": "⚡ Frontier Lab Adoption" if is_en else "⚡ Frontier Lab Adoption (Найм R&D лабораторій)",
    "stage_early": "🔬 Early Research Pre-print" if is_en else "🔬 Early Research Pre-print (Фундаментальний алгоритм)",
    "time_1_3": "~1–3 Months" if is_en else "~1–3 місяці",
    "time_3_6": "~3–6 Months" if is_en else "~3–6 місяців",
    "time_6_9": "~6–9 Months" if is_en else "~6–9 місяців",
    "horizon_title": "🤖 Autonomy Horizon of Frontier Models" if is_en else "🤖 Горизонт автономності топ-моделей",
    "circle_title": "🎯 Control vs Autonomy of AI Actions" if is_en else "🎯 Контроль і автономність дій ШІ",
    "method_expander": "ℹ️ Methodology: Autonomy Horizon Chart" if is_en else "ℹ️ Методологія: графік горизонту автономності",
    "circle_method_expander": "📐 Methodology: Control vs Autonomy Action Circle" if is_en else "📐 Методологія розрахунку: Контроль та автономність дій ШІ"
}

with col_reg:
    reg_options = ["All Regions", "Europe", "US", "APAC"] if is_en else ["Всі регіони", "Europe", "US", "APAC"]
    selected_region = st.selectbox(
        "Region Scope",
        options=reg_options,
        index=0,
        label_visibility="collapsed"
    )

reg_lookup = "All Regions" if selected_region in ["All Regions", "Всі регіони"] else selected_region
filtered_skills = df_skills_base.copy()

if reg_lookup != "All Regions":
    target_reg = "EU" if reg_lookup == "Europe" else reg_lookup
    if "region" in filtered_skills.columns:
        filtered_skills = filtered_skills[filtered_skills["region"].isin([reg_lookup, target_reg])]
    elif not filtered_skills.empty and "vacancy_count" in filtered_skills.columns:
        weights = {"US": 0.55, "Europe": 0.30, "APAC": 0.15}
        w = weights.get(reg_lookup, 1.0)
        filtered_skills["vacancy_count"] = (filtered_skills["vacancy_count"] * w).round().astype(int)
        filtered_skills = filtered_skills[filtered_skills["vacancy_count"] > 0]

with st.sidebar:
    st.markdown("#### Filters" if is_en else "#### Фільтри")
    tracks = ["All"] + (sorted(df_skills_base["track"].dropna().unique().tolist()) if not df_skills_base.empty and "track" in df_skills_base.columns else [])
    selected_track = st.selectbox("Role Track" if is_en else "Напрям ролі", tracks)

    levels = ["All"] + (sorted(df_skills_base["experience_level"].dropna().unique().tolist()) if not df_skills_base.empty and "experience_level" in df_skills_base.columns else [])
    selected_level = st.selectbox("Seniority Scope" if is_en else "Рівень досвіду", levels)

    top_n = st.slider("Top Skills" if is_en else "Топ навичок", 5, 20, 8)
    if st.button("🔄 Sync Feed" if is_en else "🔄 Оновити фід", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

total_skills = int(filtered_skills["vacancy_count"].sum()) if not filtered_skills.empty and "vacancy_count" in filtered_skills.columns else 0
batch_size = df_health["records_ingested"].iloc[0] if not df_health.empty and "records_ingested" in df_health.columns else 0

top_skill_name = "N/A"
top_skill_share = 0
velocity_skill = "N/A"

if not filtered_skills.empty and "vacancy_count" in filtered_skills.columns:
    agg_temp = filtered_skills.groupby("skill_name")["vacancy_count"].sum().sort_values(ascending=False)
    if not agg_temp.empty and total_skills > 0:
        top_skill_name = agg_temp.index[0]
        top_skill_share = int((agg_temp.iloc[0] / total_skills) * 100)
        if len(agg_temp) > 1:
            velocity_skill = agg_temp.index[1]

st.markdown(f"""
<div class="market-status-bar">
  <div class="market-indicator">
    <span class="indicator-title">{L['dominant']} ({reg_lookup})</span>
    <span class="indicator-val">{top_skill_name} <span class="badge-blue">{top_skill_share}%</span></span>
  </div>
  <div class="market-indicator">
    <span class="indicator-title">{L['velocity']}</span>
    <span class="indicator-val">{velocity_skill} <span class="badge-green">⚡ +45% WoW</span></span>
  </div>
  <div class="market-indicator" style="margin-top:2px;">
    <span class="indicator-title">{L['indexed']}</span>
    <span class="indicator-val">{total_skills:,}</span>
  </div>
  <div class="market-indicator" style="margin-top:2px;">
    <span class="indicator-title">{L['status']}</span>
    <span class="indicator-val"><span style="color:#16a34a;">●</span> {L['live']} <span style="font-size:0.7rem; color:#64748b; font-weight:500;">(+{batch_size})</span></span>
  </div>
</div>
""", unsafe_allow_html=True)

def apply_clean_layout(fig, height=250):
    fig.update_layout(
        height=height,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(showgrid=True, gridcolor="#f1f5f9", tickfont=dict(color="#475569", size=9), dtick=1),
        yaxis=dict(showgrid=False, tickfont=dict(color="#0f172a", size=10)),
        showlegend=False
    )
    return fig

selected_view = st.selectbox(
    "Select Analytics View",
    options=[L["tab_demand"], L["tab_future"]],
    index=0,
    label_visibility="collapsed"
)

if selected_view == L["tab_demand"]:
    f_chart_skills = filtered_skills.copy()
    if selected_track != "All" and "track" in f_chart_skills.columns:
        f_chart_skills = f_chart_skills[f_chart_skills["track"] == selected_track]
    if selected_level != "All" and "experience_level" in f_chart_skills.columns:
        f_chart_skills = f_chart_skills[f_chart_skills["experience_level"] == selected_level]

    if not f_chart_skills.empty:
        agg = (
            f_chart_skills.groupby("skill_name", as_index=False)["vacancy_count"]
            .sum()
            .sort_values(by="vacancy_count", ascending=True)
            .tail(top_n)
        )
        calc_height = max(180, len(agg) * 26 + 35)
        fig_skills = px.bar(
            agg,
            x="vacancy_count",
            y="skill_name",
            orientation="h",
            text="vacancy_count",
            color_discrete_sequence=["#0284c7"]
        )
        fig_skills = apply_clean_layout(fig_skills, height=calc_height)
        fig_skills.update_traces(
            textposition="inside",
            insidetextfont=dict(color="#ffffff", size=10),
            width=0.42
        )
        st.plotly_chart(fig_skills, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
    else:
        st.caption(f"{L['empty_skills']} {reg_lookup}.")

else:
    if not df_arxiv.empty:
        st.caption(L["future_caption"])
        total_items = len(df_arxiv)
        for idx, row in df_arxiv.iterrows():
            readiness_pct = int(min(92, max(38, 85 - (idx * (45 // max(1, total_items - 1))))))

            if readiness_pct >= 75:
                stage_label = L["stage_high"]
                time_est = L["time_1_3"]
            elif readiness_pct >= 55:
                stage_label = L["stage_frontier"]
                time_est = L["time_3_6"]
            else:
                stage_label = L["stage_early"]
                time_est = L["time_6_9"]

            raw_summary = row.get("signal_summary", "")
            role_display = str(row.get("predicted_role", "Emerging Specialist"))
            desc_display = raw_summary

            try:
                parsed_json = json.loads(raw_summary)
                if isinstance(parsed_json, dict):
                    desc_display = parsed_json.get("en" if is_en else "ua", "")
                    if is_en:
                        role_display = parsed_json.get("role_en", role_display)
                    else:
                        role_display = parsed_json.get("role_ua", role_display)
            except Exception:
                pass

            st.markdown(f"""
            <div class="future-role-card">
              <div class="future-role-header">
                <span class="future-role-title">{role_display}</span>
                <span class="future-role-badge">{L['market_lead']} {time_est}</span>
              </div>
              <div class="lead-time-wrap">
                <div class="lead-time-meta">
                  <span>{stage_label}</span>
                  <span>{L['stack_readiness']} <b>{readiness_pct}%</b></span>
                </div>
                <div class="lead-time-bg">
                  <div class="lead-time-bar" style="width: {readiness_pct}%;"></div>
                </div>
              </div>
              <div class="future-skill-tag">⚡ Tech: {row.get('predicted_skill', 'N/A')}</div>
              <div class="future-role-desc">{desc_display}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption(L["empty_arxiv"])

# ==========================================
# ЧАСОВИЙ ГРАФІК: ГОРИЗОНТ АВТОНОМНОСТІ МОДЕЛІ-ЛІДЕРА
# ==========================================
INSTRUMENT_CEILING_H = 16.0   # стеля METR T50
REQUIRED_COLS = {"source", "metric", "model_name", "release_date", "value_hours"}
HISTORY_START = pd.Timestamp("2023-01-01")   # за замовчуванням показуємо еру GPT-4 і далі

# series_id = "<source>|<metric>" -> (підпис EN, підпис UA, колір)
SERIES_META = {
    "METR|T50":                 ("METR T50 (software, 50%)",      "METR T50 (ПЗ-завдання, 50%)", "#4f46e5"),
    "METR|T80":                 ("METR T80 (80%)",                "METR T80 (80%)",              "#0284c7"),
    "UK_AISI_CYBER|T80":        ("UK AISI cyber T80",             "UK AISI кібер T80",           "#dc2626"),
    "REDWOOD_NOCOT|NOCOT_T50":  ("Redwood no-CoT T50 (auxiliary)", "Redwood no-CoT T50 (допоміжна)", "#64748b"),
}
DEFAULT_SERIES = ["METR|T50", "UK_AISI_CYBER|T80"]

def series_label(sid):
    meta = SERIES_META.get(sid)
    if meta:
        return meta[0] if is_en else meta[1]
    return sid.replace("|", " ")

def series_color(sid):
    meta = SERIES_META.get(sid)
    return meta[2] if meta else "#0f766e"

def short_name(name):
    """gpt-5-2025-08-07 -> gpt-5 (дата в кінці назви зайва для підпису)."""
    return re.sub(r"[-_]?20\d{2}-?\d{2}-?\d{2}$", "", str(name))

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin-bottom:8px;'>{L['horizon_title']}</div>", unsafe_allow_html=True)

if df_hor.empty or not REQUIRED_COLS.issubset(df_hor.columns):
    st.info("Data synchronization in progress." if is_en else "Триває збір даних горизонтів.")
    if hor_error:
        st.caption(f"⚠️ fct_autonomy_horizons: {hor_error}")
    elif not df_hor.empty:
        st.caption("⚠️ Missing columns: " + ", ".join(sorted(REQUIRED_COLS - set(df_hor.columns))))
else:
    d = df_hor.copy()
    d["release_date"] = pd.to_datetime(d["release_date"], errors="coerce", utc=True).dt.tz_localize(None)
    d["value_hours"] = pd.to_numeric(d["value_hours"], errors="coerce")
    d = d.dropna(subset=["release_date", "value_hours", "model_name"])
    d = d[d["value_hours"] > 0]
    d["series_id"] = d["source"].astype(str) + "|" + d["metric"].astype(str)

    available = sorted(d["series_id"].unique().tolist(), key=lambda s: (s not in SERIES_META, list(SERIES_META).index(s) if s in SERIES_META else 0, s))
    defaults = [s for s in DEFAULT_SERIES if s in available] or available[:1]

    selected_series = st.multiselect(
        "Series" if is_en else "Ряди даних",
        options=available,
        default=defaults,
        format_func=series_label,
        label_visibility="collapsed"
    )
    show_full = st.checkbox(
        "Full history (from 2019)" if is_en else "Вся історія (з 2019)",
        value=False
    )

    d_sel = d[d["series_id"].isin(selected_series)]
    if not show_full:
        d_sel = d_sel[d_sel["release_date"] >= HISTORY_START]

    if not selected_series:
        st.caption("Select at least one series." if is_en else "Оберіть хоча б один ряд.")
    elif d_sel.empty:
        st.caption("No data for the selected series." if is_en else "Немає даних для обраних рядів.")
    else:
        show_ceiling = "METR|T50" in selected_series
        x_min, x_max = d_sel["release_date"].min(), d_sel["release_date"].max()
        y_lo = d_sel["value_hours"].min() / 1.5
        y_hi = d_sel["value_hours"].max()
        if show_ceiling:
            y_hi = max(y_hi, INSTRUMENT_CEILING_H)
        y_hi *= 2

        fig_tl = go.Figure()
        notes = []

        for sid in selected_series:
            sub = d_sel[d_sel["series_id"] == sid].sort_values("release_date")
            # одна точка на модель (найсвіжіший замір)
            sub = sub.drop_duplicates(subset=["model_name"], keep="last").sort_values("release_date").reset_index(drop=True)
            if sub.empty:
                continue

            color = series_color(sid)
            name = series_label(sid)
            sub["frontier"] = sub["value_hours"].cummax()
            sub["is_record"] = sub["value_hours"] >= sub["frontier"]
            recs = sub[sub["is_record"]].reset_index(drop=True)
            others = sub[~sub["is_record"]]

            # решта моделей - напівпрозорі точки
            if not others.empty:
                fig_tl.add_trace(go.Scatter(
                    x=others["release_date"], y=others["value_hours"],
                    mode="markers",
                    marker=dict(size=6, color=color, opacity=0.3),
                    text=others["model_name"],
                    hovertemplate="%{text}<br>%{y:.2f} h<extra>" + name + "</extra>",
                    showlegend=False
                ))

            # лінія лідера (ступінчаста) для легенди
            fig_tl.add_trace(go.Scatter(
                x=sub["release_date"], y=sub["frontier"],
                mode="lines",
                line=dict(color=color, width=2, shape="hv"),
                name=name,
                hoverinfo="skip"
            ))

            # рекордсмени: підписуємо лише останніх п'ять, щоб текст не накладався
            n_rec = len(recs)
            label_from = max(0, n_rec - 5)
            rec_text = [short_name(n) if i >= label_from else "" for i, n in enumerate(recs["model_name"])]
            rec_pos = ["top left" if i % 2 == 0 else "bottom right" for i in range(n_rec)]
            fig_tl.add_trace(go.Scatter(
                x=recs["release_date"], y=recs["value_hours"],
                mode="markers+text",
                marker=dict(size=9, color=color),
                text=rec_text,
                textposition=rec_pos,
                textfont=dict(size=9, color="#0f172a"),
                hovertext=recs["model_name"],
                hovertemplate="%{hovertext}<br>%{y:.2f} h<extra>" + name + "</extra>",
                showlegend=False
            ))

            # підпис: останній вимір + час подвоєння лідера
            line = f"**{name}:** " + (
                f"last measurement {sub['release_date'].max():%Y-%m-%d}" if is_en
                else f"останній вимір {sub['release_date'].max():%Y-%m-%d}"
            )
            if n_rec >= 2:
                span_days = (recs["release_date"].iloc[-1] - recs["release_date"].iloc[0]).days
                growth = recs["value_hours"].iloc[-1] / recs["value_hours"].iloc[0]
                if span_days > 0 and growth > 1:
                    dbl_months = span_days / 30.4 / np.log2(growth)
                    line += (f", leader doubling ~{dbl_months:.1f} mo." if is_en
                             else f", подвоєння лідера ~{dbl_months:.1f} міс.")
            notes.append(line)

        # стеля METR малюється лінією-трасою, а не add_hline: add_hline ламає автомасштаб логарифмічної осі
        if show_ceiling:
            fig_tl.add_trace(go.Scatter(
                x=[x_min, x_max], y=[INSTRUMENT_CEILING_H, INSTRUMENT_CEILING_H],
                mode="lines+text",
                line=dict(color="#dc2626", width=1, dash="dash"),
                text=["", "METR ceiling 16h" if is_en else "Стеля METR 16 год"],
                textposition="top left",
                textfont=dict(size=9, color="#dc2626"),
                hoverinfo="skip",
                showlegend=False
            ))

        # круглі позначки осі в годинах замість SI-префіксів (k, M, G, T)
        tick_vals = [v for v in (0.001, 0.01, 0.1, 1, 10, 100, 1000) if y_lo <= v <= y_hi]
        fig_tl.update_layout(
            height=360,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            margin=dict(l=10, r=10, t=10, b=10),
            font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
            xaxis=dict(showgrid=False, range=[x_min - pd.Timedelta(days=45), x_max + pd.Timedelta(days=45)]),
            yaxis=dict(
                type="log",
                range=[float(np.log10(y_lo)), float(np.log10(y_hi))],
                tickvals=tick_vals,
                ticktext=[f"{v:g}" for v in tick_vals],
                showgrid=True,
                gridcolor="#f1f5f9",
                title="Horizon, hours" if is_en else "Горизонт, год"
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=9)),
            showlegend=True
        )
        st.plotly_chart(fig_tl, use_container_width=True, config={'displayModeBar': False})

        for n in notes:
            st.caption(n)
        st.caption(
            "Series come from different benchmarks and are not directly comparable."
            if is_en else
            "Ряди походять з різних бенчмарків і не є прямо порівнюваними."
        )

# ==========================================
# КОЛО КОНТРОЛЮ / АВТОНОМНОСТІ ДІЙ ШІ
# ==========================================
CIRCLE_SEGMENTS = {
    "approved":       ("🟢 Full Control",        "🟢 Full Control",              "#15803d"),
    "oversight":      ("🟩 Перегляд",             "🟩 Revision",                  "#86efac"),
    "auto_in_bounds": ("🟡 Автономно в межах",   "🟡 Autonomous within bounds",  "#f59e0b"),
    "out_of_bounds":  ("🔴 Поза межами",          "🔴 Out of bounds",              "#dc2626"),
}

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin-bottom:8px;'>{L['circle_title']}</div>", unsafe_allow_html=True)

df_circ = df_circ_raw.copy()
circ_keys = list(CIRCLE_SEGMENTS.keys())

is_demo = df_circ.empty
if is_demo:
    df_circ = pd.DataFrame([{
        "period": "2026-10",
        "approved": 25,
        "oversight": 45,
        "auto_in_bounds": 29,
        "out_of_bounds": 1,
        "source_type": "live_telemetry",
        "source_reference": "Baseline Simulator"
    }])
    st.caption("⚠️ " + ("Using simulation baseline (Syncing live audit logs...)" if is_en else "Використовуються базові метрики (Синхронізація логів аудиту...)"))

for k in circ_keys:
    if k not in df_circ.columns:
        df_circ[k] = 0
    df_circ[k] = pd.to_numeric(df_circ[k], errors="coerce").fillna(0)

circ_periods = sorted(df_circ["period"].astype(str).unique().tolist(), reverse=True)
selected_p = st.selectbox("Period", circ_periods, index=0, label_visibility="collapsed")

matching_rows = df_circ[df_circ["period"].astype(str) == selected_p]
if not matching_rows.empty:
    circ_row = matching_rows.iloc[0]
    lang_idx = 1 if is_en else 0
    circ_labels = [CIRCLE_SEGMENTS[k][lang_idx] for k in circ_keys]
    circ_values = [int(circ_row[k]) for k in circ_keys]
    circ_colors = {CIRCLE_SEGMENTS[k][lang_idx]: CIRCLE_SEGMENTS[k][2] for k in circ_keys}
    circ_total = sum(circ_values)

    # Чистка значень від NaN
    source_type_val = circ_row.get("source_type")
    if pd.isna(source_type_val) or not str(source_type_val).strip() or str(source_type_val) == "nan":
        source_type_val = "live_telemetry"
    else:
        source_type_val = str(source_type_val).strip()

    source_ref_val = circ_row.get("source_reference")
    if pd.isna(source_ref_val) or not str(source_ref_val).strip() or str(source_ref_val) == "nan":
        source_ref_val = "AI Incident Database & Inspect Evals"
    else:
        source_ref_val = str(source_ref_val).strip()

    if circ_total == 0:
        st.caption("No data for this period." if is_en else "Немає даних за цей період.")
    else:
        fig_circ = px.pie(
            names=circ_labels,
            values=circ_values,
            hole=0,
            color=circ_labels,
            color_discrete_map=circ_colors,
        )
        fig_circ.update_traces(
            textinfo="percent+label",
            textposition="outside",
            sort=False,
            showlegend=False
        )
        fig_circ.update_layout(
            height=300,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            margin=dict(l=20, r=20, t=20, b=20),
            font=dict(color="#0f172a", size=10, family="-apple-system, BlinkMacSystemFont, Segoe UI")
        )
        st.plotly_chart(fig_circ, use_container_width=True, config={'displayModeBar': False})

        red_share = (circ_values[3] / circ_total) * 100 if circ_total > 0 else 0
        total_lbl = "Total actions" if is_en else "Всього дій"
        skynet_lbl = "100% = Skynet" if is_en else "100% = «Скайнет»"
        oob_lbl = "Out of bounds" if is_en else "Поза межами"
        lower_bound_txt = (
            "Lower bound: only verified incidents & container violations."
            if is_en
            else "Нижня межа: лише верифіковані інциденти та порушення ізоляції."
        )

        if source_type_val == "Frontier System Card Audit":
            badge_title = "🛡️ Verified Benchmark:" if is_en else "🛡️ Верифіковано:"
            badge_line = f"<span style='color:#0284c7; font-weight:700;'>{badge_title} Frontier System Card Audit</span> <span style='color:#475569;'>({source_ref_val})</span>"
        else:
            badge_title = "● Telemetry stream:" if is_en else "● Потік телеметрії:"
            badge_line = f"<span style='color:#16a34a; font-weight:700;'>{badge_title}</span> <span style='color:#475569;'>{source_ref_val}</span>"

        info_html = (
            f"<div style='font-size:0.76rem; color:#64748b; line-height:1.5; margin-top:4px; padding-left:2px;'>"
            f"<b>{total_lbl}:</b> {circ_total:,} &nbsp;|&nbsp; "
            f"<b>{oob_lbl}:</b> <span style='color:#dc2626; font-weight:700;'>{red_share:.2f}%</span> "
            f"<span style='color:#94a3b8;'>({skynet_lbl})</span><br>"
            f"<div style='margin-top:2px; margin-bottom:2px;'>{badge_line}</div>"
            f"<span style='color:#94a3b8;'>{lower_bound_txt}</span>"
            f"</div>"
        )
        st.markdown(info_html, unsafe_allow_html=True)

# ==========================================
# МЕТОДОЛОГІЯ: ГОРИЗОНТ АВТОНОМНОСТІ ТА ACTION CIRCLE
# ==========================================
with st.expander(L["method_expander"]):
    if is_en:
        st.markdown(f"""
        **Autonomy Horizon of the Leading Model:**
        * **Horizon:** the length of a task (in hours of human expert work) that a model completes with a given reliability: 50% ($T_{{50}}$) or 80% ($T_{{80}}$). It is the main measure of model autonomy.
        * **Leader line:** the running maximum of the horizon over release dates. Labeled points are the models that set a new record; faint points are other measured models.
        * **Sources (kept separate):** METR via Epoch AI, CC BY 4.0 (software and research-engineering tasks), UK AISI (cyber tasks) and, as an auxiliary signal, Redwood Research (no chain-of-thought reasoning). Different benchmarks and reliability levels are never merged into one curve.
        * **Log scale:** the vertical axis is logarithmic, so steady exponential growth appears as a straight line. The doubling time is computed between the first and the latest record of each series.
        * **Instrument ceiling:** METR $T_{{50}}$ is reliable only up to about **{INSTRUMENT_CEILING_H:.0f} hours**; above it values are censored and the real horizon may be longer. METR data is no longer updated, so that series ends at its last measurement.
        """)
    else:
        st.markdown(f"""
        **Горизонт автономності моделі-лідера:**
        * **Горизонт:** довжина завдання (у годинах роботи експерта-людини), яке модель виконує із заданою надійністю: 50% ($T_{{50}}$) або 80% ($T_{{80}}$). Це головний вимір автономності моделі.
        * **Лінія лідера:** поточний максимум горизонту за датами релізу. Підписані точки це моделі, що встановили новий рекорд; напівпрозорі точки це інші виміряні моделі.
        * **Джерела (окремо):** METR через Epoch AI, CC BY 4.0 (програмні та дослідницько-інженерні завдання), UK AISI (кібер-завдання) і, як допоміжний сигнал, Redwood Research (міркування без ланцюжка думок). Різні бенчмарки й рівні надійності ніколи не зшиваються в одну криву.
        * **Логарифмічна шкала:** вертикальна вісь логарифмічна, тому стабільне експоненційне зростання виглядає прямою лінією. Час подвоєння рахується між першим і останнім рекордом кожного ряду.
        * **Стеля вимірювань:** METR $T_{{50}}$ надійний лише приблизно до **{INSTRUMENT_CEILING_H:.0f} годин**; вище значення цензуровані, реальний горизонт може бути більшим. Дані METR більше не оновлюються, тому цей ряд закінчується на останньому виміру.
        """)

with st.expander(L["circle_method_expander"]):
    if is_en:
        st.markdown("""
        ### 1. Mathematical Balance & 100% Boundary
        The Action Circle visualizes the complete distribution of recorded AI agent behaviors across standardized benchmarks and audit registries:

        $$N_{\\text{total}} = N_{\\text{approved}} + N_{\\text{oversight}} + N_{\\text{auto}} + N_{\\text{out}}$$

        $$P_i = \\frac{N_i}{N_{\\text{total}}} \\times 100\\%$$

        **Formula Explanation & Parameters:**
        * **$N_{\\text{total}}$** — total volume of evaluated agent actions for the given month ($100\\%$ of the pie circle).
        * **$P_i$** — calculated percentage share of each individual operational segment ($i$).
        * **$N_{\\text{approved}}$ (🟢 Full Control):** actions requiring prior human confirmation (human-in-the-loop: merged PRs, authorized tool executions).
        * **$N_{\\text{oversight}}$ (🟩 Revision):** autonomous agent actions submitted for human inspection and code review before release.
        * **$N_{\\text{auto}}$ (🟡 Auto in bounds):** autonomous agent steps executed cleanly inside assigned tool scopes and container sandboxes.
        * **$N_{\\text{out}}$ (🔴 Out of bounds):** verified container escapes, permission bypasses, or documented real-world systemic failures.

        ---

        ### 2. Operational Control Segments
        * **🟢 Full Control (`approved`):** Direct human authorization for every major action.
        * **🟩 Revision (`oversight`):** Autonomous work completed by the model that remains subject to human code audits and post-hoc verification.
        * **🟡 Autonomous within bounds (`auto_in_bounds`):** Routine autonomous operations contained entirely within allowed execution limits.
        * **🔴 Out of bounds (`out_of_bounds`):** Incidents where systems overrode permissions, attempted sandbox escapes, or caused verified disruptions.

        ---

        ### 3. Primary Data Registries & Verification
        * **Frontier System Cards & Framework Audits:** Evaluated releases (Anthropic RSP ASL-3, OpenAI Preparedness, DeepMind FSF) take top priority when published, providing ground-truth verification of red-teaming anomalies and jailbreak bounds.
        * **AI Incident Database (`incidentdatabase.ai`):** Public GraphQL API capturing verified real-world systemic failures and boundary violations.
        * **SWE-bench Verified (`swe-bench/SWE-bench`):** Standard repository telemetry tracking pull request oversight and post-execution engineering audits.
        * **UK AISI Inspect Platform (`UKGovernmentBEIS/inspect_ai`):** Linux/Docker execution logs documenting tool approvals and sandbox-isolated autonomous steps.
        """)
    else:
        st.markdown("""
        ### 1. Математичний баланс та правило 100%
        Кругова діаграма показує точний розподіл усіх зафіксованих дій ШІ-агентів у тестових середовищах та реєстрах аудиту у співвідношенні 1:1:

        $$N_{\\text{total}} = N_{\\text{approved}} + N_{\\text{oversight}} + N_{\\text{auto}} + N_{\\text{out}}$$

        $$P_i = \\frac{N_i}{N_{\\text{total}}} \\times 100\\%$$

        **Пояснення змінних формули:**
        * **$N_{\\text{total}}$** — загальна кількість зафіксованих дій агентів за звітний місяць, що становить повні $100\\%$ кругової діаграми.
        * **$P_i$** — розрахована відсоткова частка відповідного сектора ($i$) на діаграмі.
        * **$N_{\\text{approved}}$ (🟢 Full Control):** дії під прямим контролем людини (оператор особисто погодив виконання команди чи злив Pull Request).
        * **$N_{\\text{oversight}}$ (🟩 Перегляд):** автономні дії моделі, передані людині на пост-фактум аудит, код-рев'ю та валідацію.
        * **$N_{\\text{auto}}$ (🟡 Автономно в межах):** завдання, успішно закриті системою самостійно без виходу за дозволені рамки інструментів і пісочниці.
        * **$N_{\\text{out}}$ (🔴 Поза межами):** верифіковані інциденти порушення рамок: спроби виходу з контейнера (sandbox escape), несанкціоновані системні виклики або зафіксовані збої.

        ---

        ### 2. Сегменти контролю дій
        * **🟢 Full Control (`approved`):** Обов'язкове попереднє людське погодження дій (Human-in-the-loop).
        * **🟩 Перегляд (`oversight`):** Автономні дії з подальшим обов'язковим аудитом та контролем результатів.
        * **🟡 Автономно в межах (`auto_in_bounds`):** Безпечна автономна робота агента у межах лімітів і дозволеного стеку.
        * **🔴 Поза межами (`out_of_bounds`):** Вихід з-під контролю або спроби порушення обмежень безпеки.

        ---

        ### 3. Первинні джерела та верифікація зрізів
        * **Frontier System Cards & Framework Audits:** Офіційні звіти лабораторій (Anthropic RSP, OpenAI Preparedness, DeepMind FSF), що мають найвищий пріоритет під час релізів нових моделей та слугують базою калібрування червоного сектора.
        * **AI Incident Database (`incidentdatabase.ai`):** Відкритий GraphQL API для фіксації підтверджених інцидентів порушення рамок безпеки.
        * **SWE-bench Verified (`swe-bench/SWE-bench`):** Журнали виконання інженерних завдань і статусів аудиту Pull Requests.
        * **UK AISI Inspect Platform (`UKGovernmentBEIS/inspect_ai`):** Логи виконання інструментальних викликів у захищених контейнерах Linux/Docker.
        """)
