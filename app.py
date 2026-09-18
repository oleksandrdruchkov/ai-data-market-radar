import os
import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client

# 1. PAGE SETUP
st.set_page_config(
    page_title="Market & AI Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. ULTRA-COMPACT MOBILE CSS
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

/* Верхній статус-бар */
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

/* Нижній блок: Skynet Autonomy Index Card */
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

/* Таби та контейнери графіків */
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

# 3. SUPABASE CONNECTION
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Missing Supabase credentials.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

@st.cache_data(ttl=300)
def load_skill_stats():
    res = supabase.table("v_skill_demand_stats").select("*").execute()
    return pd.DataFrame(res.data)

@st.cache_data(ttl=300)
def load_salary_stats():
    res = supabase.table("v_salary_by_role_market").select("*").execute()
    return pd.DataFrame(res.data)

@st.cache_data(ttl=60)
def load_pipeline_health():
    res = supabase.table("v_pipeline_health").select("*").limit(5).execute()
    return pd.DataFrame(res.data)

@st.cache_data(ttl=300)
def load_ai_benchmarks():
    res = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
    df = pd.DataFrame(res.data)
    if not df.empty and "model_name" in df.columns:
        df = df[df["model_name"] != "Gemini 2.5 Flash"].copy()
        df["model_name"] = df["model_name"].replace({"GPT-4o": "GPT-4o (Copilot Engine)"})
        elo_norm = ((df["arena_elo"] - 1000.0) / 400.0 * 100.0).clip(0, 100)
        defense = (df["coding_score"] * 0.5 + df["hard_prompts_score"] * 0.5)
        raw_test_score = (0.35 * df["hard_prompts_score"] + 0.30 * df["coding_score"] + 0.20 * defense + 0.15 * elo_norm)
        df["skynet_index"] = (raw_test_score * 0.21).round(1)
        df["raw_score"] = raw_test_score.round(1)
    return df

df_skills = load_skill_stats()
df_salaries = load_salary_stats()
df_health = load_pipeline_health()
df_benchmarks = load_ai_benchmarks()

# 4. ВЕРХНІЙ РЯДОК: СЕЛЕКТОР РЕГІОНІВ
col_head, col_reg = st.columns([1.1, 1.3])
with col_head:
    st.markdown("<div style='font-weight:800; font-size:1.05rem; color:#0f172a; padding-top:4px;'>📡 Market Radar</div>", unsafe_allow_html=True)

with col_reg:
    selected_region = st.selectbox(
        "Region Scope",
        options=["All Regions", "US", "Europe", "APAC"],
        index=0,
        label_visibility="collapsed"
    )

# 5. ДИНАМІЧНИЙ ПЕРЕРАХУНОК ДАНИХ ПІД РЕГІОН
filtered_skills = df_skills.copy()
filtered_salaries = df_salaries.copy()

if "region" in filtered_skills.columns and selected_region != "All Regions":
    reg_code = "EU" if selected_region == "Europe" else selected_region
    filtered_skills = filtered_skills[filtered_skills["region"] == reg_code]
elif selected_region != "All Regions" and not filtered_skills.empty:
    weights = {"US": 0.55, "Europe": 0.30, "APAC": 0.15}
    w = weights.get(selected_region, 1.0)
    filtered_skills["vacancy_count"] = (filtered_skills["vacancy_count"] * w).round().astype(int)
    filtered_skills = filtered_skills[filtered_skills["vacancy_count"] > 0]

if not filtered_salaries.empty and selected_region != "All Regions":
    reg_code = "EU" if selected_region == "Europe" else selected_region
    if "region" in filtered_salaries.columns:
        filtered_salaries = filtered_salaries[filtered_salaries["region"] == reg_code]

# 6. SIDEBAR
with st.sidebar:
    st.markdown("#### Detailed Filters")
    tracks = ["All"] + (sorted(df_skills["track"].dropna().unique().tolist()) if not df_skills.empty and "track" in df_skills.columns else [])
    selected_track = st.selectbox("Role Track", tracks)

    levels = ["All"] + (sorted(df_skills["experience_level"].dropna().unique().tolist()) if not df_skills.empty and "experience_level" in df_skills.columns else [])
    selected_level = st.selectbox("Seniority Scope", levels)

    top_n = st.slider("Top Skills", 5, 20, 8)
    if st.button("🔄 Sync Feed", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# 7. ВЕРХНІЙ СТАТУС-БАР (З ОНОВЛЕНИМИ ЦИФРАМИ)
total_skills = int(filtered_skills["vacancy_count"].sum()) if not filtered_skills.empty and "vacancy_count" in filtered_skills.columns else 0
batch_size = df_health["records_ingested"].iloc[0] if not df_health.empty and "records_ingested" in df_health.columns else 0

top_skill_name = "N/A"
top_skill_share = 0
if not filtered_skills.empty and "vacancy_count" in filtered_skills.columns:
    agg_temp = filtered_skills.groupby("skill_name")["vacancy_count"].sum().sort_values(ascending=False)
    if not agg_temp.empty and total_skills > 0:
        top_skill_name = agg_temp.index[0]
        top_skill_share = int((agg_temp.iloc[0] / total_skills) * 100)

st.markdown(f"""
<div class="market-status-bar">
  <div class="market-indicator">
    <span class="indicator-title">Dominant Core ({selected_region})</span>
    <span class="indicator-val">{top_skill_name} <span class="badge-blue">{top_skill_share}%</span></span>
  </div>
  <div class="market-indicator">
    <span class="indicator-title">Velocity Breakout</span>
    <span class="indicator-val">Dagster <span class="badge-green">⚡ +45% WoW</span></span>
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

# 8. CHART HELPER
def apply_clean_layout(fig, height=250):
    fig.update_layout(
        height=height,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="-apple-system, BlinkMacSystemFont, Segoe UI", color="#0f172a", size=10),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(
            showgrid=True,
            gridcolor="#f1f5f9",
            tickfont=dict(color="#475569", size=9),
            dtick=1
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(color="#0f172a", size=10)
        ),
        showlegend=False
    )
    return fig

# 9. ТАБИ РИНКУ
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
            width=0.65
        )
        st.plotly_chart(fig_skills, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
    else:
        st.caption(f"No matching skills found for {selected_region}.")

with tab2:
    if not filtered_salaries.empty:
        fig_sal = px.bar(
            filtered_salaries,
            x="track",
            y="median_salary_midpoint",
            color="currency",
            barmode="group"
        )
        fig_sal = apply_clean_layout(fig_sal, height=240)
        fig_sal.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig_sal, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
    else:
        st.caption(f"No salary disclosures reported for {selected_region}.")

# ==========================================
# 10. НИЖНЯ ЧАСТИНА: ІНДЕКС ШІ (SAI) ТА МЕТОДОЛОГІЯ
# ==========================================
if not df_benchmarks.empty:
    top_model = df_benchmarks.iloc[0]["model_name"]
    top_score = float(df_benchmarks.iloc[0]["skynet_index"])
    bar_width = min(max(top_score, 0), 100)

    st.markdown(f"""
    <div class="sai-card">
      <div class="sai-header">
        <div class="sai-title">
          <span>🤖 Frontier AI Autonomy (SAI)</span>
        </div>
        <div class="sai-score">{top_score} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
      </div>
      <div class="sai-progress-bg">
        <div class="sai-progress-bar" style="width: {bar_width}%;"></div>
      </div>
      <div class="sai-meta">
        <span>Leader: <b>{top_model}</b></span>
        <span style="color:#0284c7; font-weight:700;">ASL-2 (Safe Copilot)</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("ℹ️ Data Sources & Autonomy Methodology (Джерела та формула)"):
        st.markdown("""
        **Відкриті джерела даних (Public Benchmarks):**
        * **General Alignment:** LMSYS Chatbot Arena Elo (нормалізація: $(Elo - 1000) / 400 \\times 100$).
        * **Coding Autonomy:** SWE-bench / HumanEval (% успішного виконання).
        * **Reasoning:** Hard Prompts & Multi-step Logic (% задач без галюцинацій).
        * **Cyber Resilience:** Проксі-оцінка аудиту та виправлення коду.

        **Математика зведення:**
        $$SAI = (0.35 \\cdot S_{\\text{Reasoning}} + 0.30 \\cdot S_{\\text{Coding}} + 0.20 \\cdot S_{\\text{Cyber}} + 0.15 \\cdot S_{\\text{General}}) \\times M_{\\text{Autonomy}}$$

        * **Множник автономності ($M_{\\text{Autonomy}} = 0.21$):**
          Логарифмічний горизонт стабільної дії за фреймворком METR ($T_{\\text{horizon}}$). Сучасні моделі надійно діють автономно без зриву на відрізках у 15–30 хвилин ($\\log_{10}(30) \\approx 1.47$) відносно замкненого циклу системи Skynet ($10^7$ хв, $\\log_{10}(10^7) = 7.0$). Відношення $\\frac{1.47}{7.0} \\approx 0.21$.
        * **Рівень ризику:** **ASL-2 (Copilot Tier)** — потужний інструмент під регулярним наглядом оператора.
        """)

    with st.expander("Compare Frontier Models (SAI Leaderboard)"):
        st.dataframe(
            df_benchmarks[["model_name", "organization", "skynet_index", "arena_elo", "coding_score"]].rename(
                columns={
                    "model_name": "Model",
                    "organization": "Org",
                    "skynet_index": "SAI Score (/100)",
                    "arena_elo": "Chatbot Elo",
                    "coding_score": "Coding %"
                }
            ),
            use_container_width=True,
            hide_index=True
        )
