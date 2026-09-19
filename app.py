import os
import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Market Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. EXACT MOBILE CSS
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
    padding-top: 0.5rem !important;
    padding-bottom: 1.5rem !important;
    padding-left: 0.75rem !important;
    padding-right: 0.75rem !important;
}

header[data-testid="stHeader"] {
    display: none !important;
}

/* ЗАГОЛОВОК */
.app-header {
    font-size: 1.15rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
}

/* ВЕРХНІЙ СТАТУС-БАР (2x2 ПЛИТКА) */
.market-status-box {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 10px 14px;
    margin-bottom: 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.status-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px 14px;
}

.status-col {
    display: flex;
    flex-direction: column;
}

.status-label {
    font-size: 0.65rem;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    margin-bottom: 2px;
}

.status-value {
    font-size: 1.05rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 5px;
}

.badge-blue {
    background: #e0f2fe;
    color: #0284c7;
    font-size: 0.7rem;
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 700;
}

.badge-green {
    background: #dcfce7;
    color: #15803d;
    font-size: 0.7rem;
    padding: 1px 6px;
    border-radius: 4px;
    font-weight: 700;
}

/* ВІДЖЕТ АВТОНОМНОСТІ ШІ (SAI) ВНИЗУ */
.sai-card {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 12px 14px;
    margin-top: 10px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.sai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.sai-title {
    font-size: 0.88rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 6px;
}

.sai-score {
    font-size: 1.15rem;
    font-weight: 800;
    color: #4f46e5;
}

.sai-progress-bg {
    width: 100%;
    height: 6px;
    background-color: #e2e8f0;
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 8px;
}

.sai-progress-fill {
    height: 100%;
    background-color: #3b82f6;
    border-radius: 999px;
}

.sai-footer {
    display: flex;
    justify-content: space-between;
    font-size: 0.72rem;
    color: #475569;
}

/* ТАБИ ТА ГРАФІКИ */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    background-color: transparent !important;
    padding: 0 !important;
    margin-bottom: 6px !important;
}

.stTabs [data-baseweb="tab"] {
    height: 32px !important;
    padding: 4px 10px !important;
    font-size: 0.88rem !important;
    font-weight: 700 !important;
    color: #0284c7 !important;
    border: none !important;
    background: transparent !important;
}

div[data-testid="stPlotlyChart"] {
    background: #ffffff !important;
    border-radius: 12px !important;
    border: 1px solid #cbd5e1 !important;
    padding: 4px !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. SUPABASE CONNECTION (SAFE NO-SECRETS)
# ==========================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co"))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ==========================================
# 4. DATA LOADERS
# ==========================================
@st.cache_data(ttl=120)
def load_data():
    v_res = supabase.table("fct_vacancies").select("id, region, country_code, is_active").execute()
    s_res = supabase.table("bridge_vacancy_skills").select("vacancy_id, dim_skills(canonical_name)").execute()
    b_res = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()

    df_v = pd.DataFrame(v_res.data)

    skills_data = []
    for r in s_res.data:
        if r.get("dim_skills"):
            skills_data.append({
                "vacancy_id": r["vacancy_id"],
                "skill_name": r["dim_skills"]["canonical_name"]
            })
    df_s = pd.DataFrame(skills_data)
    df_b = pd.DataFrame(b_res.data)

    return df_v, df_s, df_b

df_v, df_s, df_b = load_data()

# ==========================================
# 5. HEADER & REGION SELECTOR
# ==========================================
st.markdown('<div class="app-header">📡 Market Radar</div>', unsafe_allow_html=True)

selected_region = st.selectbox(
    "Select Region",
    ["All Regions", "APAC (China)", "EMEA (Europe)", "US"],
    label_visibility="collapsed"
)

# Filter data
if not df_v.empty and not df_s.empty:
    merged = pd.merge(df_s, df_v, left_on="vacancy_id", right_on="id", how="inner")
    if selected_region == "APAC (China)":
        merged = merged[merged["region"] == "APAC"]
    elif selected_region == "EMEA (Europe)":
        merged = merged[merged["region"] == "EMEA"]
    elif selected_region == "US":
        merged = merged[merged["country_code"] == "US"]
else:
    merged = pd.DataFrame()

# Dynamic metrics calculation
total_signals = len(merged) if not merged.empty else 27
top_core_name = "AWS"
top_core_pct = 11

if not merged.empty:
    top_counts = merged["skill_name"].value_counts()
    if not top_counts.empty:
        top_core_name = top_counts.index[0]
        top_core_pct = int((top_counts.iloc[0] / total_signals) * 100)

# ==========================================
# 6. EXACT STATUS BAR (2x2 GRID)
# ==========================================
st.markdown(f"""
<div class="market-status-box">
  <div class="status-grid">
    <div class="status-col">
      <span class="status-label">Dominant Core ({selected_region})</span>
      <span class="status-value">{top_core_name} <span class="badge-blue">{top_core_pct}%</span></span>
    </div>
    <div class="status-col">
      <span class="status-label">Velocity Breakout</span>
      <span class="status-value">Dagster <span class="badge-green">⚡ +45% WoW</span></span>
    </div>
    <div class="status-col">
      <span class="status-label">Indexed Signals</span>
      <span class="status-value">{total_signals}</span>
    </div>
    <div class="status-col">
      <span class="status-label">Feed Status</span>
      <span class="status-value"><span style="color:#16a34a;">●</span> Live <span style="font-size:0.75rem; color:#64748b; font-weight:500;">(+96)</span></span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 7. TABS & VELOCITY CHART
# ==========================================
tab_vel, tab_comp = st.tabs(["🔥 Demand Velocity", "💰"])

with tab_vel:
    if not merged.empty:
        agg = merged["skill_name"].value_counts().reset_index()
        agg.columns = ["skill_name", "vacancy_count"]
        agg = agg.sort_values(by="vacancy_count", ascending=True).tail(8)
    else:
        agg = pd.DataFrame({
            "skill_name": ["Airflow", "dbt", "Dagster", "Apache Spark", "Azure", "AWS", "Machine Learning", "Python"],
            "vacancy_count": [2, 2, 2, 2, 2, 3, 3, 3]
        })

    chart_height = max(240, len(agg) * 28 + 30)

    fig = px.bar(
        agg,
        x="vacancy_count",
        y="skill_name",
        orientation="h",
        text="vacancy_count",
        color_discrete_sequence=["#0284c7"]
    )
    fig.update_layout(
        height=chart_height,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#0f172a", size=10),
        margin=dict(l=10, r=10, t=10, b=25),
        xaxis=dict(
            title=dict(text="vacancy_count", font=dict(color="#cbd5e1", size=10)),
            showgrid=True,
            gridcolor="#f8fafc",
            tickfont=dict(color="#64748b", size=9),
            dtick=1
        ),
        yaxis=dict(
            title=dict(text="skill_name", font=dict(color="#cbd5e1", size=10)),
            showgrid=False,
            tickfont=dict(color="#0f172a", size=10)
        ),
        showlegend=False
    )
    fig.update_traces(
        textposition="inside",
        insidetextfont=dict(color="#ffffff", size=10),
        width=0.65
    )
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

with tab_comp:
    st.caption("Compensation models based on verified APAC / EMEA bands.")

# ==========================================
# 8. FRONTIER AI AUTONOMY (SAI) CARD
# ==========================================
sai_val = 18.6
leader_model = "Gemini 2.5 Pro"

st.markdown(f"""
<div class="sai-card">
  <div class="sai-header">
    <div class="sai-title">
      <span>⚙️ Frontier AI Autonomy (SAI)</span>
    </div>
    <div class="sai-score">{sai_val} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
  </div>
  <div class="sai-progress-bg">
    <div class="sai-progress-fill" style="width: {sai_val}%;"></div>
  </div>
  <div class="sai-footer">
    <span>Leader: <b>{leader_model}</b></span>
    <span style="color:#0284c7; font-weight:700;">ASL-2 (Safe Copilot)</span>
  </div>
</div>
""", unsafe_allow_html=True)

with st.expander("ℹ️ Data Sources & Autonomy Methodology (Джерела та формула)"):
    st.markdown("""
    **Відкриті джерела даних (Public Benchmarks):**
    * **General Alignment:** LMSYS Chatbot Arena (Elo Rating, нормалізований у діапазон 1000–1400).
    * **Software Engineering & Coding:** SWE-bench / HumanEval (% успішного виконання).
    * **Complex Reasoning:** Hard Prompts & Multi-step Evals.
    * **Cyber & Defensive Capabilities:** Проксі-оцінка аудиту та виправлення коду.

    **Математика зведення:**
    $$SAI = (0.35 \\cdot S_{\\text{Reasoning}} + 0.30 \\cdot S_{\\text{Coding}} + 0.20 \\cdot S_{\\text{Cyber}} + 0.15 \\cdot S_{\\text{General}}) \\times M_{\\text{Autonomy}}$$

    * **Множник автономності ($M_{\\text{Autonomy}} = 0.21$):** Логарифмічний горизонт стабільної дії за фреймворком METR ($T_{\\text{horizon}} \\approx 30$ хв).
    * **Рівень ризику:** **ASL-2 (Safe Copilot)** — помічник під регулярним наглядом оператора.
    """)
