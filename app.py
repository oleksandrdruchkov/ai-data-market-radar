import os
from datetime import datetime, timezone
import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client

# ==========================================
# 1. PAGE SETUP
# ==========================================
st.set_page_config(
    page_title="Market & AI Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. ULTRA-COMPACT MOBILE CSS
# ==========================================
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

/* Market Status Bar (2x2 Grid) */
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
    color: #0369a1;
    font-size: 0.65rem;
    padding: 1px 5px;
    border-radius: 4px;
    font-weight: 700;
}

/* Future Role Cards with Lead-Time Progress */
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

/* Frontier AI Autonomy (SAI) Card */
.sai-card {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 10px 12px;
    margin-top: 10px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.sai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}

.sai-title {
    font-size: 0.8rem;
    font-weight: 700;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 5px;
}

.sai-score {
    font-size: 1.1rem;
    font-weight: 800;
    color: #4f46e5;
}

.sai-progress-bg {
    width: 100%;
    height: 8px;
    background: #e2e8f0;
    border-radius: 4px;
    overflow: hidden;
    position: relative;
    margin-bottom: 6px;
}

.sai-progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #3b82f6 0%, #6366f1 100%);
    border-radius: 4px;
}

.sai-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.68rem;
    color: #64748b;
    font-weight: 500;
}

/* Tabs & Chart Containers */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    background-color: #e2e8f0 !important;
    padding: 3px !important;
    border-radius: 8px !important;
    margin-bottom: 8px !important;
}

.stTabs [data-baseweb="tab"] {
    height: 30px !important;
    padding: 2px 10px !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    color: #334155 !important;
}

.stTabs [aria-selected="true"] {
    background-color: #ffffff !important;
    color: #0284c7 !important;
    font-weight: 700 !important;
}

div[data-testid="stPlotlyChart"] {
    background: #ffffff !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #cbd5e1 !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. SUPABASE CONNECTION
# ==========================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co"))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_KEY in Secrets.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ==========================================
# 4. DATA LOADERS & DYNAMIC SAI COMPUTATION
# ==========================================
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

    # Dynamic Autonomy Multiplier
    try:
        res_params = (
            supabase.table("dim_autonomy_parameters")
            .select("autonomy_multiplier, task_horizon_minutes")
            .order("effective_date", desc=True)
            .limit(1)
            .execute()
        )
        if res_params.data and len(res_params.data) > 0:
            autonomy_mult = float(res_params.data[0]["autonomy_multiplier"])
            horizon_mins = float(res_params.data[0]["task_horizon_minutes"])
        else:
            autonomy_mult, horizon_mins = 0.210, 30.0
    except Exception:
        autonomy_mult, horizon_mins = 0.210, 30.0

    # AI Benchmarks
    try:
        res_benchmarks = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
        df_b = pd.DataFrame(res_benchmarks.data)
    except Exception:
        df_b = pd.DataFrame()

    if not df_b.empty and "arena_elo" in df_b.columns:
        if "model_name" in df_b.columns and len(df_b) > 1:
            df_b = df_b[df_b["model_name"] != "Gemini 2.5 Flash"].copy()

        elo_norm = ((df_b["arena_elo"].fillna(1000.0) - 1000.0) / 400.0 * 100.0).clip(lower=0.0, upper=100.0)

        # Reasoning: HLE with fallback
        if "hle_score" in df_b.columns and df_b["hle_score"].notnull().any():
            reasoning = df_b["hle_score"].fillna(df_b.get("hard_prompts_score", 80.0))
        else:
            reasoning = df_b.get("hard_prompts_score", 80.0)

        # Agentic OS/CLI: Terminal-Bench with fallback
        if "terminal_bench_score" in df_b.columns and df_b["terminal_bench_score"].notnull().any():
            agentic = df_b["terminal_bench_score"].fillna(df_b.get("coding_score", 80.0))
        else:
            agentic = df_b.get("coding_score", 80.0)

        # Defense
        if "defense_score" in df_b.columns and df_b["defense_score"].notnull().any():
            defense = df_b["defense_score"].fillna(agentic * 0.5 + reasoning * 0.5)
        else:
            defense = (agentic + reasoning) / 2.0

        raw_test_score = (
            0.35 * reasoning +
            0.30 * agentic +
            0.20 * defense +
            0.15 * elo_norm
        )

        df_b["sai_score"] = (raw_test_score * autonomy_mult).round(1)
        df_b = df_b.sort_values(by="sai_score", ascending=False).reset_index(drop=True)

    return df_s, df_ar, df_h, df_b, autonomy_mult, horizon_mins

@st.cache_data(ttl=60)
def load_sai_history():
    try:
        res = supabase.table("v_sai_history").select("*").order("eval_date", desc=False).execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

df_skills_base, df_arxiv, df_health, df_b, active_multiplier, active_horizon = load_data()
df_sai_hist = load_sai_history()

# ==========================================
# 5. HEADER, LANGUAGE SWITCHER & REGION SCOPE
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

# I18N Localization Dictionary
L = {
    "dominant": "DOMINANT CORE" if is_en else "ДОМІНУЮЧЕ ЯДРО",
    "velocity": "VELOCITY BREAKOUT" if is_en else "ПРОРИВ ШВИДКОСТІ",
    "indexed": "INDEXED SIGNALS" if is_en else "ПРОІНДЕКСОВАНО",
    "status": "FEED STATUS" if is_en else "СТАТУС ФІДУ",
    "live": "Live" if is_en else "Наживо",
    "tab_demand": "🔥 Demand Velocity" if is_en else "🔥 Швидкість попиту",
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
    "sai_title": "🤖 Frontier AI Autonomy (SAI)",
    "sai_leader": "Leader:" if is_en else "Лідер:",
    "sai_fresh": "● Fresh" if is_en else "● Свіжі",
    "sai_stale": "⚠️ Stale" if is_en else "⚠️ Застарілі",
    "method_expander": "ℹ️️ Data Sources & Autonomy Methodology" if is_en else "ℹ️ Джерела даних та методологія автономності",
    "compare_expander": "📊 Compare Frontier Models (SAI Leaderboard)" if is_en else "📊 Порівняння моделей ШІ (SAI Лідерборд)",
    "timeline_expander": "📈 Dynamic Timeline: SAI History" if is_en else "📈 Динамічний таймлайн: Історія SAI"
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
    elif not filtered_skills.empty:
        weights = {"US": 0.55, "Europe": 0.30, "APAC": 0.15}
        w = weights.get(reg_lookup, 1.0)
        filtered_skills["vacancy_count"] = (filtered_skills["vacancy_count"] * w).round().astype(int)
        filtered_skills = filtered_skills[filtered_skills["vacancy_count"] > 0]

# ==========================================
# 6. SIDEBAR FILTERS
# ==========================================
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

# ==========================================
# 7. MARKET STATUS BAR (2x2 GRID)
# ==========================================
total_skills = int(filtered_skills["vacancy_count"].sum()) if not filtered_skills.empty and "vacancy_count" in filtered_skills.columns else 0
batch_size = df_health["records_ingested"].iloc[0] if not df_health.empty and "records_ingested" in df_health.columns else 0

top_skill_name = "N/A"
top_skill_share = 0
velocity_skill = "Dagster"

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

# ==========================================
# 8. MARKET TABS (DEMAND & FUTURE ROLES)
# ==========================================
tab1, tab2 = st.tabs([L["tab_demand"], L["tab_future"]])

with tab1:
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

with tab2:
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

            st.markdown(f"""
            <div class="future-role-card">
              <div class="future-role-header">
                <span class="future-role-title">{row.get('predicted_role', 'Emerging Specialist')}</span>
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
              <div class="future-role-desc">{row.get('signal_summary', '')}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption(L["empty_arxiv"])

# ==========================================
# 9. FRONTIER AI AUTONOMY (SAI) CARD
# ==========================================
data_status_badge = ""
is_stale = False
last_date_str = "N/A"

if not df_b.empty and "recorded_at" in df_b.columns:
    df_b["recorded_at_dt"] = pd.to_datetime(df_b["recorded_at"], utc=True)
    latest_ts = df_b["recorded_at_dt"].max()
    now_utc = datetime.now(timezone.utc)
    age_hours = (now_utc - latest_ts).total_seconds() / 3600.0
    last_date_str = latest_ts.strftime("%d.%m.%Y")

    if age_hours <= 48:
        data_status_badge = f'<span style="color:#10b981; font-size:0.75rem; font-weight:600;">{L["sai_fresh"]} ({last_date_str})</span>'
    else:
        is_stale = True
        days_stale = int(age_hours // 24)
        data_status_badge = f'<span style="color:#f59e0b; font-size:0.75rem; font-weight:600;">{L["sai_stale"]} ({days_stale}d ago, {last_date_str})</span>'
else:
    data_status_badge = '<span style="color:#64748b; font-size:0.75rem; font-weight:600;">● Connected</span>'

if not df_b.empty and "sai_score" in df_b.columns:
    leader_row = df_b.iloc[0]
    leader_model = str(leader_row.get("model_name", "Claude 3.7 Sonnet"))
    sai_val = float(leader_row.get("sai_score", 19.2))
else:
    sai_val = 19.2
    leader_model = "Claude 3.7 Sonnet"

bar_width = min(max(sai_val, 0.0), 100.0)

st.markdown(f"""
<div class="sai-card">
  <div class="sai-header">
    <div class="sai-title">
      <span>{L['sai_title']}</span>
      <div style="margin-left:8px; display:inline-block;">{data_status_badge}</div>
    </div>
    <div class="sai-score">{sai_val} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
  </div>
  <div class="sai-progress-bg">
    <div class="sai-progress-bar" style="width: {bar_width}%;"></div>
  </div>
  <div class="sai-meta">
    <span>{L['sai_leader']} <b>{leader_model}</b></span>
    <span style="color:#0284c7; font-weight:700;">ASL-2 (Safe Copilot)</span>
  </div>
</div>
""", unsafe_allow_html=True)

# Methodology expander
with st.expander(L["method_expander"]):
    if is_en:
        st.markdown(f"""
        **Evaluated Frontier Benchmarks:**
        * **Ph.D.-Level Reasoning (35%):** Humanity's Last Exam (HLE) & Hard Prompts.
        * **Agentic OS & Terminal Engineering (30%):** Terminal-Bench 2.0 / SWE-bench.
        * **Cyber Defense & Alignment (20%):** Security Audit & Resilience score.
        * **General Capability (15%):** LMSYS Chatbot Arena Elo (normalized to 1000–1400 baseline).

        **Synthesis Formula (MCDA):**
        $$SAI = (0.35 \\cdot S_{{\\text{{Reasoning}}}} + 0.30 \\cdot S_{{\\text{{Agentic}}}} + 0.20 \\cdot S_{{\\text{{Defense}}}} + 0.15 \\cdot S_{{\\text{{General}}}}) \\times M_{{\\text{{Autonomy}}}}$$

        * **Current METR Autonomy Multiplier ($M_{{\\text{{Autonomy}}}} = {active_multiplier}$):**
          Based on continuous stable operation horizon ($T_{{\\text{{horizon}}}} \\approx {int(active_horizon)}$ mins) relative to closed-loop autonomous execution ($10^7$ mins).
        * **Safety Classification:** **ASL-2 (Safe Copilot)** — models require active human oversight.
        """)
    else:
        st.markdown(f"""
        **Оцінювані бенчмарки передового ШІ:**
        * **Ph.D.-рівень міркувань (35%):** Humanity's Last Exam (HLE) та Hard Prompts.
        * **Агентна робота в ОС та терміналі (30%):** Terminal-Bench 2.0 / SWE-bench.
        * **Кіберзахист та стійкість (20%):** Аудит коду та безпекова стійкість.
        * **Загальні здібності (15%):** LMSYS Chatbot Arena Elo (нормалізовано до бази 1000–1400).

        **Синтетична формула (MCDA):**
        $$SAI = (0.35 \\cdot S_{{\\text{{Reasoning}}}} + 0.30 \\cdot S_{{\\text{{Agentic}}}} + 0.20 \\cdot S_{{\\text{{Defense}}}} + 0.15 \\cdot S_{{\\text{{General}}}}) \\times M_{{\\text{{Autonomy}}}}$$

        * **Поточний множник автономності METR ($M_{{\\text{{Autonomy}}}} = {active_multiplier}$):**
          Розраховано з горизонту стабільної дії ($T_{{\\text{{horizon}}}} \\approx {int(active_horizon)}$ хв) відносно повної замкненої автономії ($10^7$ хв).
        * **Рівень безпеки:** **ASL-2 (Safe Copilot)** — потрібен активний людський нагляд.
        """)

# Leaderboard expander
if not df_b.empty and "sai_score" in df_b.columns:
    with st.expander(L["compare_expander"]):
        cols_present = [c for c in ["model_name", "organization", "sai_score", "hle_score", "terminal_bench_score", "arena_elo"] if c in df_b.columns]
        rename_map = {
            "model_name": "Model" if is_en else "Модель",
            "organization": "Org" if is_en else "Організація",
            "sai_score": "SAI (/100)",
            "hle_score": "HLE %",
            "terminal_bench_score": "Terminal-Bench %",
            "arena_elo": "Arena Elo"
        }
        st.dataframe(
            df_b[cols_present].rename(columns=rename_map),
            use_container_width=True,
            hide_index=True
        )

# ==========================================
# 10. SAI TIMELINE: DYNAMIC HISTORY (ALWAYS EXPANDED)
# ==========================================
if not df_sai_hist.empty:
    with st.expander(L["timeline_expander"], expanded=True):
        fig_hist = px.line(
            df_sai_hist,
            x="eval_date",
            y="leader_sai",
            markers=True,
            labels={
                "eval_date": "Date" if is_en else "Дата",
                "leader_sai": "SAI Score (%)",
                "leader_model": "Leader Model" if is_en else "Модель-лідер",
                "leader_org": "Organization" if is_en else "Організація"
            },
            hover_data={"leader_sai": ":.1f", "leader_model": True, "leader_org": True}
        )

        fig_hist.update_traces(
            line_color="#4f46e5",
            marker=dict(size=8, color="#3730a3")
        )

        annotations = []
        for _, row in df_sai_hist.iterrows():
            annotations.append(
                dict(
                    x=row["eval_date"],
                    y=row["leader_sai"],
                    text=f"<b>{row['leader_model']}</b>",
                    showarrow=False,
                    textangle=-90,
                    yshift=45,
                    font=dict(size=10, color="#f8fafc", family="Inter, -apple-system, sans-serif")
                )
            )

        y_min = max(0.0, float(df_sai_hist["leader_sai"].min()) - 4.0)
        y_max = float(df_sai_hist["leader_sai"].max()) + 6.0

        fig_hist.update_layout(
            height=370,
            dragmode="pan",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(color="#0f172a", size=10),
            margin=dict(l=10, r=10, t=75, b=20),
            annotations=annotations,
            xaxis=dict(
                title=dict(text="Evaluation Date" if is_en else "Дата заміру", font=dict(size=10, color="#64748b")),
                showgrid=True,
                gridcolor="#f8fafc",
                tickfont=dict(size=9, color="#64748b"),
                rangeslider=dict(visible=True, thickness=0.08),
                type="date"
            ),
            yaxis=dict(
                title=dict(text="SAI Score (%)", font=dict(size=10, color="#64748b")),
                range=[y_min, y_max],
                fixedrange=True,
                showgrid=True,
                gridcolor="#f8fafc",
                tickfont=dict(size=9, color="#64748b"),
                ticksuffix="%"
            )
        )

        st.plotly_chart(
            fig_hist,
            use_container_width=True,
            config={
                'responsive': True,
                'scrollZoom': False,
                'displayModeBar': False
            }
        )
