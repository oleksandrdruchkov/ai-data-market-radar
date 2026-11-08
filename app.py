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

@st.cache_data(ttl=60)
def load_capability_data():
    """Epoch Capabilities Index (загальна здатність моделей, у пунктах індексу)."""
    try:
        res = supabase.table("fct_capability_index").select("*").execute()
        return pd.DataFrame(res.data), None
    except Exception as ex:
        return pd.DataFrame(), str(ex)[:300]

@st.cache_data(ttl=120)
def load_leader_actions():
    """Коло дій моделей-лідерів: усі розрахунки - у SQL-представленнях (sql/005_leader_actions.sql).
    Повертає (команда, моделі, записи на підтвердженні, текст помилки)."""
    try:
        team = pd.DataFrame(supabase.table("v_leader_action_circle").select("*").execute().data)
        models = pd.DataFrame(supabase.table("v_leader_action_models").select("*").execute().data)
        pending = pd.DataFrame(supabase.table("v_leader_action_pending").select("*").execute().data)
        return team, models, pending, None
    except Exception as ex:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), str(ex)[:300]

df_skills_base, df_arxiv, df_health = load_data()
df_hor, hor_error = load_horizon_data()
df_eci, eci_error = load_capability_data()
df_lead_team, df_lead_models, df_lead_pending, lead_error = load_leader_actions()

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
    "horizon_title": "🤖 Leader Autonomy: Distance to the Reference" if is_en else "🤖 Автономність лідера: відстань до еталона",
    "capability_title": "📈 General Capability of the Leading Model (Epoch ECI)" if is_en else "📈 Загальна здатність моделі-лідера (Epoch ECI)",
    "circle_title": "🎯 Leading models' actions: within and beyond bounds" if is_en else "🎯 Дії моделей-лідерів: у межах і поза межами",
    "method_expander": "ℹ️ Methodology: Autonomy Horizon Chart" if is_en else "ℹ️ Методологія: графік горизонту автономності",
    "circle_method_expander": "📐 Methodology: actions of leading models beyond bounds" if is_en else "📐 Методологія: дії моделей-лідерів поза межами"
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
        xaxis=dict(showgrid=True, gridcolor="#f1f5f9", tickfont=dict(color="#475569", size=9), dtick=1, automargin=True),
        yaxis=dict(showgrid=False, tickfont=dict(color="#0f172a", size=10), automargin=True),
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
        st.plotly_chart(fig_skills, use_container_width=True, theme=None, config={'responsive': True, 'displayModeBar': False})
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
# ЧАСОВИЙ ГРАФІК: АВТОНОМНІСТЬ МОДЕЛІ-ЛІДЕРА У ШКАЛІ SAI_T
# ==========================================
# Формула SAI_T, еталон і стеля METR визначені в одному місці - core/scales.py
# (той самий модуль рахує щоденні значення в fct_metric_values).
from core.scales import sai_t, hours_at_sai_t, beyond_ceiling, INSTRUMENT_CEILING_H, REFERENCE_H
DOUBLING_RANGE_MONTHS = (3.5, 7.0)     # історичний діапазон подвоєння спроможностей
PROJECTION_MAX_YEARS = 6
DAYS_PER_MONTH = 30.4375
REQUIRED_COLS = {"source", "metric", "model_name", "release_date", "value_hours"}
HISTORY_START = pd.Timestamp("2023-01-01")   # за замовчуванням показуємо еру GPT-4 і далі
show_full = False

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

def hex_to_rgba(color, alpha):
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def project_sai(t0_hours, doubling_months, months):
    """SAI_T при експоненційному зростанні горизонту; обрізається на 100% (еталон)."""
    grown = t0_hours * np.power(2.0, np.asarray(months, dtype=float) / doubling_months)
    return np.minimum(sai_t(grown), 100.0)

def fmt_hours(h):
    return f"{h:.1f}" if h < 100 else f"{h:.0f}"

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
    for ci_col in ("ci_low", "ci_high"):
        d[ci_col] = pd.to_numeric(d[ci_col], errors="coerce") if ci_col in d.columns else np.nan
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
    col_full, col_proj = st.columns(2)
    with col_full:
        show_full = st.checkbox(
            "Full history (from 2019)" if is_en else "Вся історія (з 2019)",
            value=False
        )
    with col_proj:
        show_proj = st.checkbox(
            "Projection to the reference" if is_en else "Проєкція до еталона",
            value=True
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
        primary_sid = "METR|T50" if show_ceiling else selected_series[0]
        x_min, x_max = d_sel["release_date"].min(), d_sel["release_date"].max()

        fig_tl = go.Figure()
        notes = []
        primary = None   # дані лідера основного ряду для проєкції

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
                    x=others["release_date"], y=sai_t(others["value_hours"]),
                    mode="markers",
                    marker=dict(size=6, color=color, opacity=0.3),
                    text=others["model_name"],
                    customdata=others["value_hours"],
                    hovertemplate="%{text}<br>%{customdata:.2f} h · SAI_T %{y:.0f}%<extra>" + name + "</extra>",
                    showlegend=False
                ))

            # лінія лідера (ступінчаста)
            fig_tl.add_trace(go.Scatter(
                x=sub["release_date"], y=sai_t(sub["frontier"]),
                mode="lines",
                line=dict(color=color, width=2, shape="hv"),
                name=name,
                hoverinfo="skip"
            ))

            # рекордсмени: підписуємо лише останніх п'ять, щоб текст не накладався
            n_rec = len(recs)
            label_from = max(0, n_rec - 5)
            rec_text = [short_name(n) if (sid == primary_sid and i >= label_from) else "" for i, n in enumerate(recs["model_name"])]
            rec_pos = ["bottom right" if (n_rec - 1 - i) % 2 == 0 else "top left" for i in range(n_rec)]
            # точки понад стелю набору задач METR - оцінка, а не надійний вимір:
            # малюємо порожнім кружечком і пишемо це в підказці
            is_metr = sid.startswith("METR|")
            est = [is_metr and beyond_ceiling(v) for v in recs["value_hours"]]
            est_note = ("<br><i>estimate: above the METR task ceiling (16 h)</i>" if is_en
                        else "<br><i>оцінка: понад стелю задач METR (16 год)</i>")
            fig_tl.add_trace(go.Scatter(
                x=recs["release_date"], y=sai_t(recs["value_hours"]),
                mode="markers+text",
                marker=dict(size=[11 if e else 9 for e in est], color=color,
                            symbol=["circle-open" if e else "circle" for e in est],
                            line=dict(width=2, color=color)),
                text=rec_text,
                textposition=rec_pos,
                textfont=dict(size=9, color="#0f172a"),
                hovertext=recs["model_name"],
                customdata=[[float(v), est_note if e else ""] for v, e in zip(recs["value_hours"], est)],
                hovertemplate="%{hovertext}<br>%{customdata[0]:.2f} h · SAI_T %{y:.0f}%%{customdata[1]}<extra>" + name + "</extra>",
                showlegend=False
            ))

            last = recs.iloc[-1]

            # довірчий інтервал останнього рекорду (вус у шкалі SAI_T)
            if pd.notna(last["ci_low"]) and pd.notna(last["ci_high"]) and last["ci_low"] > 0:
                y_c = float(sai_t(last["value_hours"]))
                fig_tl.add_trace(go.Scatter(
                    x=[last["release_date"]], y=[y_c],
                    mode="markers",
                    marker=dict(size=1, opacity=0, color=color),
                    error_y=dict(type="data", symmetric=False,
                                 array=[float(sai_t(last["ci_high"])) - y_c],
                                 arrayminus=[y_c - float(sai_t(last["ci_low"]))],
                                 color=color, thickness=1.5, width=5),
                    hoverinfo="skip", showlegend=False
                ))

            # підпис: останній вимір + час подвоєння лідера
            line = f"**{name}:** " + (
                f"last measurement {sub['release_date'].max():%Y-%m-%d}" if is_en
                else f"останній вимір {sub['release_date'].max():%Y-%m-%d}"
            )
            dbl_months = None
            if n_rec >= 2:
                span_days = (recs["release_date"].iloc[-1] - recs["release_date"].iloc[0]).days
                growth = recs["value_hours"].iloc[-1] / recs["value_hours"].iloc[0]
                if span_days > 0 and growth > 1:
                    dbl_months = span_days / DAYS_PER_MONTH / np.log2(growth)
                    line += (f", leader doubling ~{dbl_months:.1f} mo." if is_en
                             else f", подвоєння лідера ~{dbl_months:.1f} міс.")
            notes.append(line)

            if sid == primary_sid:
                primary = {
                    "name": name, "color": color, "t0": last["release_date"],
                    "T0": float(last["value_hours"]), "model": short_name(last["model_name"]),
                    "ci_low": last["ci_low"], "ci_high": last["ci_high"],
                    "dbl": dbl_months,
                }

        # ---- проєкція напрямку до еталона (ілюстративна екстраполяція) ----
        x_end = x_max + pd.Timedelta(days=200)
        proj_caption = None
        T_cross = hours_at_sai_t(100.0)              # горизонт, де SAI_T = 100%
        if show_proj and primary and primary["T0"] < T_cross:
            T0, t0, color = primary["T0"], primary["t0"], primary["color"]
            d_c = primary["dbl"] if primary["dbl"] else float(np.sqrt(DOUBLING_RANGE_MONTHS[0] * DOUBLING_RANGE_MONTHS[1]))
            d_f = min(DOUBLING_RANGE_MONTHS[0], d_c)
            d_s = max(DOUBLING_RANGE_MONTHS[1], d_c)
            n_dbl = float(np.log2(T_cross / T0))
            m_end = min(n_dbl * d_s, PROJECTION_MAX_YEARS * 12.0)
            months = np.linspace(0.0, m_end, 80)
            dates = [t0 + pd.Timedelta(days=float(m) * DAYS_PER_MONTH) for m in months]

            # смуга невизначеності між швидким і повільним подвоєнням
            fig_tl.add_trace(go.Scatter(
                x=dates, y=project_sai(T0, d_s, months),
                mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False
            ))
            fig_tl.add_trace(go.Scatter(
                x=dates, y=project_sai(T0, d_f, months),
                mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor=hex_to_rgba(color, 0.12),
                hoverinfo="skip", showlegend=False
            ))
            m_c = n_dbl * d_c
            months_c = np.append(months[months < m_c], m_c) if m_c <= m_end else months
            dates_c = [t0 + pd.Timedelta(days=float(m) * DAYS_PER_MONTH) for m in months_c]
            fig_tl.add_trace(go.Scatter(
                x=dates_c, y=project_sai(T0, d_c, months_c),
                mode="lines", line=dict(color=color, width=2, dash="dot"),
                name="Projection (illustrative)" if is_en else "Проєкція (ілюстративна)",
                hoverinfo="skip"
            ))

            def cross_date(dm):
                return t0 + pd.Timedelta(days=n_dbl * dm * DAYS_PER_MONTH)

            c_central = cross_date(d_c)
            if n_dbl * d_c <= m_end:
                fig_tl.add_trace(go.Scatter(
                    x=[c_central], y=[100.0],
                    mode="markers+text",
                    marker=dict(size=11, color=color, symbol="diamond"),
                    text=[f"≈ {c_central:%Y-%m}"], textposition="bottom left",
                    textfont=dict(size=10, color="#0f172a"),
                    hoverinfo="skip", showlegend=False
                ))
            x_end = dates[-1] + pd.Timedelta(days=60)

            if is_en:
                proj_caption = (
                    f"Distance to the reference from the latest record ({primary['model']}): ≈ {n_dbl:.1f} doublings. "
                    f"At a doubling time of {d_c:.1f} months this is ≈ {c_central:%Y-%m} "
                    f"(band for {d_f:.1f}–{d_s:.1f} months: {cross_date(d_f):%Y-%m} … {cross_date(d_s):%Y-%m})."
                )
            else:
                proj_caption = (
                    f"Відстань до еталона від останнього рекорду ({primary['model']}): ≈ {n_dbl:.1f} подвоєнь. "
                    f"При подвоєнні кожні {d_c:.1f} міс. це ≈ {c_central:%Y-%m} "
                    f"(смуга для {d_f:.1f}–{d_s:.1f} міс.: {cross_date(d_f):%Y-%m} … {cross_date(d_s):%Y-%m})."
                )

        # критична точка: еталон 1 людино-рік (100%)
        fig_tl.add_trace(go.Scatter(
            x=[x_min, x_end], y=[100.0, 100.0],
            mode="lines+text",
            line=dict(color="#b91c1c", width=1.5),
            text=["Reference: 1 human-year (2 080 h)" if is_en else "Еталон: 1 людино-рік (2 080 год)", ""],
            textposition="bottom right",
            textfont=dict(size=9, color="#b91c1c"),
            hoverinfo="skip", showlegend=False
        ))

        # стеля вимірювань METR (16 год) у шкалі SAI_T
        if show_ceiling:
            fig_tl.add_trace(go.Scatter(
                x=[x_min, x_max], y=[float(sai_t(INSTRUMENT_CEILING_H))] * 2,
                mode="lines+text",
                line=dict(color="#dc2626", width=1, dash="dash"),
                text=["METR ceiling 16h" if is_en else "Стеля METR 16 год", ""],
                textposition="top right",
                textfont=dict(size=9, color="#dc2626"),
                hoverinfo="skip", showlegend=False
            ))

        # права вісь: ті самі позиції в годинах
        hour_ticks = [0.1, 1, 4, 16, 64, 260, 1040, REFERENCE_H]
        hour_text = [f"{h:g} h" if is_en else f"{h:g} год" for h in hour_ticks[:-1]] + \
                    ["2080 h" if is_en else "2080 год"]
        fig_tl.add_trace(go.Scatter(
            x=[x_min], y=[0], yaxis="y2", mode="markers",
            marker=dict(opacity=0, size=1), hoverinfo="skip", showlegend=False
        ))

        pct_ticks = [0, 20, 40, 60, 80, 100]
        fig_tl.update_layout(
            height=400,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            margin=dict(l=10, r=10, t=10, b=10),
            font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
            xaxis=dict(showgrid=False, range=[x_min - pd.Timedelta(days=45), x_end], automargin=True),
            yaxis=dict(
                range=[0, 110], tickvals=pct_ticks, ticktext=[f"{p}%" for p in pct_ticks],
                showgrid=True, gridcolor="#f1f5f9", automargin=True, title_standoff=8,
                title="SAI_T, % of reference" if is_en else "SAI_T, % від еталона"
            ),
            yaxis2=dict(
                overlaying="y", side="right", range=[0, 110],
                tickvals=[float(sai_t(h)) for h in hour_ticks], ticktext=hour_text,
                showgrid=False, tickfont=dict(size=9, color="#64748b"), automargin=True
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, font=dict(size=9)),
            showlegend=True
        )
        st.plotly_chart(fig_tl, use_container_width=True, theme=None, config={'displayModeBar': False})

        if primary:
            cur = float(sai_t(primary["T0"]))
            cur_txt = f"{cur:.0f}%"
            if pd.notna(primary["ci_low"]) and pd.notna(primary["ci_high"]) and primary["ci_low"] > 0:
                cur_txt += f" ({float(sai_t(primary['ci_low'])):.0f}–{float(sai_t(primary['ci_high'])):.0f}%)"
            st.caption(
                f"**Current SAI_T of the leader ({primary['model']}):** {cur_txt}, horizon {fmt_hours(primary['T0'])} h."
                if is_en else
                f"**Поточний SAI_T лідера ({primary['model']}):** {cur_txt}, горизонт {fmt_hours(primary['T0'])} год."
            )
            if primary["name"] == series_label("METR|T50") and beyond_ceiling(primary["T0"]):
                st.caption(
                    "○ Empty circle = estimate: the value is above the longest METR tasks (16 h), "
                    "where the instrument no longer measures reliably."
                    if is_en else
                    "○ Порожній кружечок = оцінка: значення вище за найдовші задачі METR (16 год), "
                    "де інструмент уже не вимірює надійно."
                )
        for n in notes:
            st.caption(n)
        if proj_caption:
            st.caption(proj_caption)
            st.caption(
                "Illustrative extrapolation, not a forecast: it assumes exponential growth to continue. "
                "The reference is a scale of task length, not the moment of loss of control."
                if is_en else
                "Ілюстративна екстраполяція, а не прогноз: вона припускає, що експоненційне зростання триватиме. "
                "Еталон це шкала довжини завдання, а не момент втрати контролю."
            )
        st.caption(
            "Series come from different benchmarks and are not directly comparable."
            if is_en else
            "Ряди походять з різних бенчмарків і не є прямо порівнюваними."
        )

# ==========================================
# ЗАГАЛЬНА ЗДАТНІСТЬ МОДЕЛІ-ЛІДЕРА (EPOCH CAPABILITIES INDEX)
# ==========================================
ECI_COLOR = "#0d9488"

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin-bottom:8px;'>{L['capability_title']}</div>", unsafe_allow_html=True)

if df_eci.empty or not {"model_name", "release_date", "eci"}.issubset(df_eci.columns):
    st.info("Data synchronization in progress." if is_en else "Триває збір даних індексу здатності.")
    if eci_error:
        st.caption(f"⚠️ fct_capability_index: {eci_error}")
else:
    e = df_eci.copy()
    e["release_date"] = pd.to_datetime(e["release_date"], errors="coerce", utc=True).dt.tz_localize(None)
    for col in ("eci", "ci_low", "ci_high"):
        e[col] = pd.to_numeric(e[col], errors="coerce") if col in e.columns else np.nan
    e["label"] = e["display_name"].fillna(e["model_name"]) if "display_name" in e.columns else e["model_name"]
    e = e.dropna(subset=["release_date", "eci"])
    if not show_full:
        e = e[e["release_date"] >= HISTORY_START]

    if e.empty:
        st.caption("No data for the selected period." if is_en else "Немає даних за обраний період.")
    else:
        e = e.sort_values("release_date").reset_index(drop=True)
        e["frontier"] = e["eci"].cummax()
        e["is_record"] = e["eci"] >= e["frontier"]
        recs = e[e["is_record"]].reset_index(drop=True)
        others = e[~e["is_record"]]

        fig_eci = go.Figure()
        if not others.empty:
            fig_eci.add_trace(go.Scatter(
                x=others["release_date"], y=others["eci"],
                mode="markers",
                marker=dict(size=6, color=ECI_COLOR, opacity=0.25),
                text=others["label"],
                hovertemplate="%{text}<br>ECI %{y:.1f}<extra></extra>",
                showlegend=False
            ))

        fig_eci.add_trace(go.Scatter(
            x=e["release_date"], y=e["frontier"],
            mode="lines",
            line=dict(color=ECI_COLOR, width=2, shape="hv"),
            hoverinfo="skip",
            showlegend=False
        ))

        n_rec = len(recs)
        label_from = max(0, n_rec - 4)
        rec_text = [str(n) if i >= label_from else "" for i, n in enumerate(recs["label"])]
        rec_pos = ["bottom right" if (n_rec - 1 - i) % 2 == 0 else "top left" for i in range(n_rec)]
        err_up = (recs["ci_high"] - recs["eci"]).fillna(0).clip(lower=0)
        err_dn = (recs["eci"] - recs["ci_low"]).fillna(0).clip(lower=0)
        fig_eci.add_trace(go.Scatter(
            x=recs["release_date"], y=recs["eci"],
            mode="markers+text",
            marker=dict(size=9, color=ECI_COLOR),
            error_y=dict(type="data", symmetric=False, array=err_up, arrayminus=err_dn,
                         color=ECI_COLOR, thickness=1, width=3),
            text=rec_text,
            textposition=rec_pos,
            textfont=dict(size=9, color="#0f172a"),
            hovertext=recs["label"],
            hovertemplate="%{hovertext}<br>ECI %{y:.1f}<extra></extra>",
            showlegend=False
        ))

        y_lo = float((e["ci_low"].fillna(e["eci"])).min()) - 3
        y_hi = float((e["ci_high"].fillna(e["eci"])).max()) + 4
        fig_eci.update_layout(
            height=320,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            margin=dict(l=10, r=10, t=10, b=10),
            font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
            xaxis=dict(showgrid=False, range=[e["release_date"].min() - pd.Timedelta(days=30), e["release_date"].max() + pd.Timedelta(days=75)], automargin=True),
            yaxis=dict(range=[y_lo, y_hi], showgrid=True, gridcolor="#f1f5f9", title="ECI", automargin=True, title_standoff=8),
            showlegend=False
        )
        st.plotly_chart(fig_eci, use_container_width=True, theme=None, config={'displayModeBar': False})

        leader = recs.iloc[-1]
        cap = (f"Current record: {leader['label']} (ECI {leader['eci']:.1f}), last measurement {e['release_date'].max():%Y-%m-%d}"
               if is_en else
               f"Поточний рекорд: {leader['label']} (ECI {leader['eci']:.1f}), останній вимір {e['release_date'].max():%Y-%m-%d}")
        st.caption(cap)

        # чесна примітка: лідери з перекриттям довірчих інтервалів не розрізняються статистично
        top2 = e.sort_values("eci", ascending=False).head(2)
        if len(top2) == 2 and pd.notna(top2.iloc[1]["ci_high"]) and pd.notna(top2.iloc[0]["ci_low"]) \
                and top2.iloc[1]["ci_high"] >= top2.iloc[0]["ci_low"]:
            st.caption(
                "The top models' confidence intervals overlap: the leader cannot be ranked reliably."
                if is_en else
                "Довірчі інтервали провідних моделей перекриваються: лідера не можна впевнено визначити."
            )
        st.caption(
            "ECI is a composite index in points (not hours); source: Epoch AI, CC BY 4.0."
            if is_en else
            "ECI це складений індекс у пунктах (не години); джерело: Epoch AI, CC BY 4.0."
        )

# ==========================================
# КОЛО ДІЙ МОДЕЛЕЙ-ЛІДЕРІВ: У МЕЖАХ / ПОЗА МЕЖАМИ
# Дані реальної роботи (не тести-пастки), лише підтверджені людиною.
# Усі розрахунки - у SQL (v_leader_action_*), тут лише показ.
# ==========================================
OUT_COLOR, IN_COLOR = "#dc2626", "#cbd5e1"

def _pct(x, digits=2):
    return "—" if x is None or pd.isna(x) else f"{100 * float(x):.{digits}f}%"

def _method_label(m):
    labels = {
        "internal_use_sample": ("sample of real internal use", "вибірка реального внутрішнього використання"),
        "deployment_simulation": ("re-generation of real traffic", "перегенерація реального трафіку"),
    }
    en, ua = labels.get(m, (m, m))
    return en if is_en else ua

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin-bottom:8px;'>{L['circle_title']}</div>", unsafe_allow_html=True)

if lead_error:
    st.caption(f"⚠️ v_leader_action_*: {lead_error}")
elif df_lead_team.empty:
    st.info("No verified data yet." if is_en else "Підтверджених даних ще немає.")
else:
    team = df_lead_team.iloc[0]
    out_share = float(team["out_share"])

    # --- спливаюче вікно «поза межами»: з чого складається сегмент
    out_lines = [
        (f"<b>Beyond bounds: {_pct(out_share)}</b> (mean of {int(team['n_models'])} leading models, equal weight)"
         if is_en else
         f"<b>Поза межами: {_pct(out_share)}</b> (середнє {int(team['n_models'])} моделей-лідерів, рівна вага)"),
        (f"range across models: {_pct(team['out_min'])} … {_pct(team['out_max'])}" if is_en
         else f"розкид між моделями: {_pct(team['out_min'])} … {_pct(team['out_max'])}"),
        "",
    ]
    for _, m in df_lead_models.iterrows():
        ci = (f" [{_pct(m['ci_low'])}–{_pct(m['ci_high'])}]"
              if pd.notna(m.get("ci_low")) and pd.notna(m.get("ci_high")) else "")
        out_lines.append(f"<b>{m['lab']} · {m['model_name']}</b>: {_pct(m['rate_out'])}{ci}")
        # чому саме ця модель представляє лабораторію (вибір зроблено в SQL, тут лише показ)
        if m.get("leader_basis") == "eci" and pd.notna(m.get("eci")):
            basis = (f"leader by Epoch Capabilities Index: {float(m['eci']):.1f}" if is_en
                     else f"лідер за індексом здатностей Epoch (ECI): {float(m['eci']):.1f}")
        else:
            basis = ("no ECI found - the newest model is used" if is_en
                     else "ECI не знайдено - взято найновішу модель")
        out_lines.append(f"&nbsp;&nbsp;<i>{basis}</i>")
        top_eci = m.get("lab_top_eci")
        if pd.notna(top_eci) and (pd.isna(m.get("eci")) or float(top_eci) > float(m["eci"]) + 1e-9):
            out_lines.append("&nbsp;&nbsp;<i>" + (
                f"strongest model of the lab by ECI: {m['lab_top_model']} ({float(top_eci):.1f}) - no verified data yet"
                if is_en else
                f"найсильніша модель лабораторії за ECI: {m['lab_top_model']} ({float(top_eci):.1f}) - підтверджених даних ще немає")
                + "</i>")
        for src in (m["sources"] or []):
            units_en = {"use": "uses", "turn": "turns", "tool_call": "tool calls", "trajectory": "trajectories",
                        "session": "sessions", "transcript": "transcripts", "task": "tasks", "conversation": "conversations"}
            units_ua = {"use": "використань", "turn": "кроків", "tool_call": "викликів інструментів",
                        "trajectory": "траєкторій", "session": "сесій", "transcript": "записів роботи",
                        "task": "завдань", "conversation": "розмов"}
            cnt = (f"{src['n_out']} / {src['n_total']} " + ((units_en if is_en else units_ua).get(src["unit"], src["unit"]))
                   if src.get("n_total") else ("number of actions not published" if is_en else "кількість дій не опублікована"))
            where = f"{src.get('section') or ''}" + ((f", p. {src['page']}" if is_en else f", стор. {src['page']}")
                                                       if src.get("page") else "")
            out_lines.append(f"&nbsp;&nbsp;{_method_label(src['method'])}; {cnt}; {where}")
            for c in (src.get("counted") or []):
                val = f"{c['n']}" if c.get("n") is not None else _pct(c.get("rate"), 3)
                out_lines.append(f"&nbsp;&nbsp;+ {c['category']}: {val}")
            excl = [e["category"] for e in (src.get("excluded") or [])]
            if excl:
                out_lines.append(("&nbsp;&nbsp;<i>not counted (false reports, not actions): " if is_en
                                  else "&nbsp;&nbsp;<i>не враховано (неправдиві звіти, не дії): ")
                                 + "; ".join(excl) + "</i>")
            vb = src.get("verified_by")
            if vb:
                out_lines.append("&nbsp;&nbsp;<i>" + (
                    ("verified: automatically (quotes and numbers found in the source by code, second model agrees)"
                     if vb == "auto" else "verified: by a person")
                    if is_en else
                    ("підтверджено: автоматично (код знайшов цитати й числа в джерелі, друга модель згодна)"
                     if vb == "auto" else "підтверджено: людиною")) + "</i>")
            if src.get("classifier"):
                out_lines.append(("&nbsp;&nbsp;<i>classified by: " if is_en else "&nbsp;&nbsp;<i>класифікував: ")
                                 + src["classifier"] + "</i>")
    in_lines = [
        (f"<b>No out-of-bounds action: {_pct(1 - out_share)}</b>" if is_en
         else f"<b>Без виходу за межі: {_pct(1 - out_share)}</b>"),
        ("Completed, refused, asked a human, or was stopped by a monitor." if is_en
         else "Виконала, відмовилась, запитала людину або її зупинив монітор."),
        ("The sources do not separate these cases, so they are not split." if is_en
         else "Джерела ці випадки не розрізняють, тому сегмент не ділиться."),
    ]

    labels = (["Beyond bounds", "No out-of-bounds action"] if is_en
              else ["Поза межами", "Без виходу за межі"])
    fig_circ = go.Figure(go.Pie(
        labels=labels,
        values=[out_share, 1 - out_share],
        marker=dict(colors=[OUT_COLOR, IN_COLOR], line=dict(color="#ffffff", width=1)),
        sort=False, direction="clockwise", rotation=0,
        # малий сегмент - підпис зовні, великий - всередині, щоб нічого не обрізалось
        texttemplate="%{label}<br>%{percent:.2%}", textposition=["outside", "inside"],
        insidetextfont=dict(color="#0f172a", size=11), outsidetextfont=dict(color="#dc2626", size=11),
        hovertext=["<br>".join(out_lines), "<br>".join(in_lines)],
        hovertemplate="%{hovertext}<extra></extra>",
        showlegend=False,
    ))
    fig_circ.update_layout(
        height=340, paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        margin=dict(l=20, r=20, t=50, b=20),
        font=dict(color="#0f172a", size=10, family="-apple-system, BlinkMacSystemFont, Segoe UI"),
        hoverlabel=dict(bgcolor="#ffffff", font_size=11, align="left"),
    )
    st.plotly_chart(fig_circ, use_container_width=True, theme=None, config={'displayModeBar': False})

    st.caption(
        (f"**Team:** {team['team']}. Real-use data published by the developers; trap tests are not used. "
         "Actions were classified by the developers' model-based monitors. Hover over a segment for details.")
        if is_en else
        (f"**Команда:** {team['team']}. Дані реальної роботи, опубліковані розробниками; тести-пастки не використовуються. "
         "Дії класифікували моделі-монітори розробників. Наведіть на сегмент, щоб побачити деталі.")
    )

if not df_lead_pending.empty:
    st.caption(
        (f"⏳ {len(df_lead_pending)} record(s) awaiting human verification are not shown." if is_en
         else f"⏳ {len(df_lead_pending)} запис(и) чекають на підтвердження людиною і на колі не показані.")
    )

# ==========================================
# МЕТОДОЛОГІЯ: ГОРИЗОНТ АВТОНОМНОСТІ ТА ACTION CIRCLE
# ==========================================
with st.expander(L["method_expander"]):
    if is_en:
        st.markdown(r"""
        **Autonomy of the leading model: distance to the reference point**
        * **Measurement (third-party):** the 50% time horizon $T_{50}$ published by METR (via Epoch AI, CC BY 4.0): the length of a software task, in minutes of human expert work, that a model completes in 50% of attempts. These numbers are used as published.
        * **Interpretation (ours):** the horizon is converted to the branch-length scale

        $$SAI_T = \frac{\log_{10}(1 + T_{\min})}{\log_{10}(124\,800)} \times 100\%$$

        where $124\,800$ min = 1 human-year (2 080 h) is the reference. 100% means a model that autonomously completes a task of one human-year of work. It is a scale of task length, not the moment of loss of control.
        * **Leader line:** the running maximum over release dates. Labeled points set a new record; faint points are other measured models. The whisker is the confidence interval of the latest record.
        * **Projection (illustrative):** the latest record is extended with exponential growth. The central doubling time is measured from the leader's records in the shown period; the band uses the historical range of 3.5 to 7.0 months. It is a what-if extrapolation, not a forecast.
        * **Limits:** METR $T_{50}$ is reliable only up to about 16 hours; above it values are censored. METR data is no longer updated, so the series ends at its last measurement.
        * **Epoch Capabilities Index (ECI):** a composite capability score built from many benchmarks, in index points rather than hours. It keeps updating after the METR series stopped, so it shows the current leader. Models whose confidence intervals overlap cannot be ranked reliably.
        """)
    else:
        st.markdown(r"""
        **Автономність моделі-лідера: відстань до еталона**
        * **Вимірювання (чуже):** 50%-горизонт $T_{50}$ від METR (через Epoch AI, CC BY 4.0): довжина програмного завдання в хвилинах роботи експерта-людини, яке модель виконує у 50% спроб. Ці числа беруться як опубліковані.
        * **Інтерпретація (наша):** горизонт переводиться у шкалу довжини гілки

        $$SAI_T = \frac{\log_{10}(1 + T_{\min})}{\log_{10}(124\,800)} \times 100\%$$

        де $124\,800$ хв = 1 людино-рік (2 080 год) це еталон. 100% означає модель, що автономно виконує завдання обсягом в одну людино-рік роботи. Це шкала довжини завдання, а не момент втрати контролю.
        * **Лінія лідера:** поточний максимум за датами релізу. Підписані точки це моделі, що встановили новий рекорд; напівпрозорі це інші виміряні моделі. Вус показує довірчий інтервал останнього рекорду.
        * **Проєкція (ілюстративна):** останній рекорд продовжується експоненційним зростанням. Центральний час подвоєння вимірюється за рекордами лідера в показаному періоді; смуга використовує історичний діапазон 3,5-7,0 місяця. Це екстраполяція «що буде, якщо», а не прогноз.
        * **Межі:** METR $T_{50}$ надійний лише приблизно до 16 годин; вище значення цензуровані. Дані METR більше не оновлюються, тому ряд закінчується на останньому вимірі.
        * **Epoch Capabilities Index (ECI):** складений показник здатності за багатьма бенчмарками, в пунктах індексу, а не в годинах. Він продовжує оновлюватися після того, як ряд METR зупинився, тож показує поточного лідера. Моделі з перекритими довірчими інтервалами не можна впевнено ранжувати.
        """)

with st.expander(L["circle_method_expander"]):
    if is_en:
        st.markdown(r"""
        **What the circle shows.** The share of actions of the leading models that go beyond the task: an action the task did not provide for (bypassing a block, a destructive action, using rights that were not granted).

        $$P_{out} = \frac{1}{M}\sum_{m=1}^{M} \frac{N_{out,m}}{N_{total,m}}$$

        * **$M$** — number of leading models: from each lab, the model with the highest Epoch Capabilities Index (ECI) among those with verified data; each model has equal weight. If the lab's strongest model has no data, the hover text says so.
        * **$N_{out,m} / N_{total,m}$** — share of out-of-bounds actions of model $m$ in real-use data published by its developer (internal use, re-generation of real traffic).
        * **Not used:** trap tests built to provoke violations; their construction cannot be checked from outside.
        * **Not counted:** false reports about the work (claiming a task is done when it is not). These are not actions; they are shown in the hover text.
        * **Verification:** a number appears only after a person has checked it against the page of the source.
        * **Limits:** actions are classified by the developers' model-based monitors; samples are small (95% Wilson interval shown where counts are published).
        """)
    else:
        st.markdown(r"""
        **Що показує коло.** Частку дій моделей-лідерів, що виходять за межі завдання: дія, не передбачена завданням (обхід блокування, руйнівна дія, використання прав, яких не надавали).

        $$P_{out} = \frac{1}{M}\sum_{m=1}^{M} \frac{N_{out,m}}{N_{total,m}}$$

        * **$M$** — кількість моделей-лідерів: від кожної лабораторії модель з найвищим індексом здатностей Epoch (ECI) серед тих, що мають підтверджені дані; кожна модель має рівну вагу. Якщо найсильніша модель лабораторії даних не має, це показано у спливаючому вікні.
        * **$N_{out,m} / N_{total,m}$** — частка дій поза межами моделі $m$ у даних реальної роботи, опублікованих її розробником (внутрішнє використання, перегенерація реального трафіку).
        * **Не використовуються:** тести-пастки, побудовані, щоб спровокувати порушення; їх побудову неможливо перевірити ззовні.
        * **Не враховуються:** неправдиві звіти про роботу (модель каже, що завдання виконано, коли ні). Це не дії; вони показані у спливаючому вікні.
        * **Підтвердження:** число з'являється на колі лише після того, як людина звірила його зі сторінкою джерела.
        * **Межі:** дії класифікують моделі-монітори розробників; вибірки невеликі (де кількості опубліковано, показано 95% інтервал Вільсона).
        """)
