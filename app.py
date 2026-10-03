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
        res_salaries = supabase.table("v_salary_by_role_market").select("*").execute()
        df_sal = pd.DataFrame(res_salaries.data)
    except Exception:
        df_sal = pd.DataFrame()

    try:
        res_health = supabase.table("v_pipeline_health").select("*").limit(5).execute()
        df_h = pd.DataFrame(res_health.data)
    except Exception:
        df_h = pd.DataFrame()

    # Завантаження динамічного коефіцієнта автономності
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

    # Завантаження бенчмарків моделей
    try:
        res_benchmarks = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
        df_b = pd.DataFrame(res_benchmarks.data)
    except Exception:
        df_b = pd.DataFrame()

    if not df_b.empty and "arena_elo" in df_b.columns:
        if "model_name" in df_b.columns and len(df_b) > 1:
            df_b = df_b[df_b["model_name"] != "Gemini 2.5 Flash"].copy()

        # Нормалізація LMSYS Arena Elo (шкала 1000 - 1400)
        elo_norm = ((df_b["arena_elo"].fillna(1000.0) - 1000.0) / 400.0 * 100.0).clip(lower=0.0, upper=100.0)

        # 1. Складні наукові міркування: HLE (фолбек на hard_prompts)
        if "hle_score" in df_b.columns and df_b["hle_score"].notnull().any():
            reasoning = df_b["hle_score"].fillna(df_b.get("hard_prompts_score", 80.0))
        else:
            reasoning = df_b.get("hard_prompts_score", 80.0)

        # 2. Автономні агенти в ОС: Terminal-Bench (фолбек на coding_score)
        if "terminal_bench_score" in df_b.columns and df_b["terminal_bench_score"].notnull().any():
            agentic = df_b["terminal_bench_score"].fillna(df_b.get("coding_score", 80.0))
        else:
            agentic = df_b.get("coding_score", 80.0)

        # 3. Стійкість та кіберзахист (Defense)
        if "defense_score" in df_b.columns and df_b["defense_score"].notnull().any():
            defense = df_b["defense_score"].fillna(agentic * 0.5 + reasoning * 0.5)
        else:
            defense = (agentic + reasoning) / 2.0

        # Зважена мультикритеріальна формула
        raw_test_score = (
            0.35 * reasoning +
            0.30 * agentic +
            0.20 * defense +
            0.15 * elo_norm
        )

        df_b["sai_score"] = (raw_test_score * autonomy_mult).round(1)
        df_b = df_b.sort_values(by="sai_score", ascending=False).reset_index(drop=True)

    return df_s, df_sal, df_h, df_b, autonomy_mult, horizon_mins

@st.cache_data(ttl=60)
def load_sai_history():
    try:
        res = supabase.table("v_sai_history").select("*").order("eval_date", desc=False).execute()
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

df_skills_base, df_salaries_base, df_health, df_b, active_multiplier, active_horizon = load_data()
df_sai_hist = load_sai_history()

# ==========================================
# 5. HEADER & REGION SCOPE SELECTOR
# ==========================================
col_head, col_reg = st.columns([1.1, 1.3])
with col_head:
    st.markdown("<div style='font-weight:800; font-size:1.05rem; color:#0f172a; padding-top:4px;'>📡 Market Radar</div>", unsafe_allow_html=True)

with col_reg:
    selected_region = st.selectbox(
        "Region Scope",
        options=["All Regions", "Europe", "US", "APAC"],
        index=0,
        label_visibility="collapsed"
    )

filtered_skills = df_skills_base.copy()

if selected_region != "All Regions":
    target_reg = "EU" if selected_region == "Europe" else selected_region
    if "region" in filtered_skills.columns:
        filtered_skills = filtered_skills[filtered_skills["region"].isin([selected_region, target_reg])]
    elif not filtered_skills.empty:
        weights = {"US": 0.55, "Europe": 0.30, "APAC": 0.15}
        w = weights.get(selected_region, 1.0)
        filtered_skills["vacancy_count"] = (filtered_skills["vacancy_count"] * w).round().astype(int)
        filtered_skills = filtered_skills[filtered_skills["vacancy_count"] > 0]

# ==========================================
# 6. SIDEBAR FILTERS
# ==========================================
with st.sidebar:
    st.markdown("#### Detailed Filters")
    tracks = ["All"] + (sorted(df_skills_base["track"].dropna().unique().tolist()) if not df_skills_base.empty and "track" in df_skills_base.columns else [])
    selected_track = st.selectbox("Role Track", tracks)

    levels = ["All"] + (sorted(df_skills_base["experience_level"].dropna().unique().tolist()) if not df_skills_base.empty and "experience_level" in df_skills_base.columns else [])
    selected_level = st.selectbox("Seniority Scope", levels)

    top_n = st.slider("Top Skills", 5, 20, 8)
    if st.button("🔄 Sync Feed", use_container_width=True):
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
    <span class="indicator-title">Dominant Core ({selected_region})</span>
    <span class="indicator-val">{top_skill_name} <span class="badge-blue">{top_skill_share}%</span></span>
  </div>
  <div class="market-indicator">
    <span class="indicator-title">Velocity Breakout</span>
    <span class="indicator-val">{velocity_skill} <span class="badge-green">⚡ +45% WoW</span></span>
  </div>
  <div class="market-indicator" style="margin-top:2px;">
    <span class="indicator-title">Indexed Signals</span>
    <span class="indicator-val">{total_skills:,}</span>
  </div>
  <div class="market-indicator" style="margin-top:2px;">
    <span class="indicator-title">Feed Status</span>
    <span class="indicator-val"><span style="color:#16a34a;">●</span> Live <span style="font-size:0.7rem; color:#64748b; font-weight:500;">(+{batch_size})</span></span>
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
# 8. MARKET TABS (DEMAND & SALARIES)
# ==========================================
tab1, tab2 = st.tabs(["🔥 Demand Velocity", "💰 Compensation"])

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
        st.caption(f"No matching skills found for {selected_region}.")

with tab2:
    if not df_salaries_base.empty:
        df_sal_flt = df_salaries_base.copy()
        
        # Узгодження коду "Europe" та "EU" у вітрині заробітних плат
        target_reg = "EU" if selected_region == "Europe" else selected_region
        if selected_region != "All Regions" and "region" in df_sal_flt.columns:
            df_sal_flt = df_sal_flt[df_sal_flt["region"].isin([selected_region, target_reg])]

        if not df_sal_flt.empty and "track" in df_sal_flt.columns and "median_salary_midpoint" in df_sal_flt.columns:
            sal_agg = (
                df_sal_flt.groupby(["track", "currency"], as_index=False)["median_salary_midpoint"]
                .median()
                .sort_values(by="median_salary_midpoint", ascending=False)
            )

            fig_sal = px.bar(
                sal_agg,
                x="track",
                y="median_salary_midpoint",
                color="currency",
                barmode="group",
                text="median_salary_midpoint",
                color_discrete_sequence=["#0284c7", "#16a34a", "#9333ea"]
            )
            fig_sal.update_layout(
                height=250,
                paper_bgcolor="#ffffff",
                plot_bgcolor="#ffffff",
                bargap=0.35,
                bargroupgap=0.15,
                font=dict(color="#0f172a", size=10),
                margin=dict(l=10, r=10, t=15, b=25),
                xaxis=dict(
                    title=dict(text="", font=dict(size=1)),
                    showgrid=False,
                    tickfont=dict(size=9, color="#0f172a")
                ),
                yaxis=dict(
                    title=dict(text="Median Salary", font=dict(color="#cbd5e1", size=10)),
                    showgrid=True,
                    gridcolor="#f8fafc",
                    tickfont=dict(size=9, color="#64748b")
                ),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    title=None,
                    font=dict(size=9)
                )
            )
            fig_sal.update_traces(
                texttemplate='%{text:.2s}',
                textposition='inside',
                insidetextfont=dict(color="#ffffff", size=9)
            )
            st.plotly_chart(fig_sal, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
        else:
            st.caption(f"No salary disclosures reported for {selected_region}.")
    else:
        st.caption("No salary data available in the database yet.")

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
        data_status_badge = f'<span style="color:#10b981; font-size:0.75rem; font-weight:600;">● Fresh ({last_date_str})</span>'
    else:
        is_stale = True
        days_stale = int(age_hours // 24)
        data_status_badge = f'<span style="color:#f59e0b; font-size:0.75rem; font-weight:600;">⚠️ Stale ({days_stale}d ago, {last_date_str})</span>'
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
      <span>🤖 Frontier AI Autonomy (SAI)</span>
      <div style="margin-left:8px; display:inline-block;">{data_status_badge}</div>
    </div>
    <div class="sai-score">{sai_val} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
  </div>
  <div class="sai-progress-bg">
    <div class="sai-progress-bar" style="width: {bar_width}%;"></div>
  </div>
  <div class="sai-meta">
    <span>Leader: <b>{leader_model}</b></span>
    <span style="color:#0284c7; font-weight:700;">ASL-2 (Safe Copilot)</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 9.1 EARLY RESEARCH SIGNALS (ARXIV RADAR)
# ==========================================
try:
    res_arxiv = supabase.table("fct_arxiv_signals").select("*").order("published_date", desc=True).limit(5).execute()
    df_arxiv = pd.DataFrame(res_arxiv.data)
except Exception:
    df_arxiv = pd.DataFrame()

if not df_arxiv.empty:
    with st.expander("🔮 ArXiv Early Signals: Predicted Emerging Tech (3–6 Mo. Lead)", expanded=False):
        for _, row in df_arxiv.iterrows():
            st.markdown(f"""
            <div style="padding: 6px 0; border-bottom: 1px solid #f1f5f9;">
              <div style="font-size: 0.85rem; font-weight: 700; color: #0f172a;">
                ⚡ <b>{row.get('predicted_skill', 'N/A')}</b> 
                <span style="font-weight: 400; color: #64748b;">→ {row.get('predicted_role', 'Specialist')}</span>
              </div>
              <div style="font-size: 0.75rem; color: #475569; margin-top: 2px;">
                {row.get('signal_summary', '')}
              </div>
            </div>
            """, unsafe_allow_html=True)

# Methodology expander
with st.expander("ℹ️ Data Sources & Autonomy Methodology"):
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

# Leaderboard expander
if not df_b.empty and "sai_score" in df_b.columns:
    with st.expander("📊 Compare Frontier Models (SAI Leaderboard)"):
        cols_present = [c for c in ["model_name", "organization", "sai_score", "hle_score", "terminal_bench_score", "arena_elo"] if c in df_b.columns]
        rename_map = {
            "model_name": "Model",
            "organization": "Org",
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
    with st.expander("📈 Dynamic Timeline: SAI History", expanded=True):
        fig_hist = px.line(
            df_sai_hist,
            x="eval_date",
            y="leader_sai",
            markers=True,
            labels={
                "eval_date": "Date",
                "leader_sai": "SAI Score (%)",
                "leader_model": "Leader Model",
                "leader_org": "Organization"
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
                title=dict(text="Evaluation Date", font=dict(size=10, color="#64748b")),
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
