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

.app-header {
    font-size: 1.15rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
}

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
# 3. SUPABASE CONNECTION
# ==========================================
SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co"))
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ==========================================
# 4. DATA LOADERS & SAI COMPUTATION
# ==========================================
@st.cache_data(ttl=60)
def load_data():
    res_skills = supabase.table("v_skill_demand_stats").select("*").execute()
    res_benchmarks = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()

    df_s = pd.DataFrame(res_skills.data)
    df_b = pd.DataFrame(res_benchmarks.data)

    # Динамічний розрахунок індексу автономності (SAI)
    if not df_b.empty and "arena_elo" in df_b.columns:
        # Виключаємо допоміжні/Flash-моделі за наявності основних
        if "model_name" in df_b.columns and len(df_b) > 1:
            df_b = df_b[df_b["model_name"] != "Gemini 2.5 Flash"].copy()

        elo_norm = ((df_b["arena_elo"] - 1000.0) / 400.0 * 100.0).clip(lower=0, upper=100)
        
        # Defense Score (якщо відсутній у схемі, використовуємо середнє Coding + Reasoning)
        if "defense_score" in df_b.columns and df_b["defense_score"].notnull().any():
            defense = df_b["defense_score"]
        else:
            c_score = df_b["coding_score"] if "coding_score" in df_b.columns else 80.0
            r_score = df_b["hard_prompts_score"] if "hard_prompts_score" in df_b.columns else 80.0
            defense = (c_score * 0.5 + r_score * 0.5)

        hard_p = df_b["hard_prompts_score"] if "hard_prompts_score" in df_b.columns else 80.0
        coding_s = df_b["coding_score"] if "coding_score" in df_b.columns else 80.0

        raw_test_score = (
            0.35 * hard_p +
            0.30 * coding_s +
            0.20 * defense +
            0.15 * elo_norm
        )
        
        # Горизонт стабільної дії METR (~30 хв): коефіцієнт 0.21
        df_b["sai_score"] = (raw_test_score * 0.21).round(1)
        df_b = df_b.sort_values(by="sai_score", ascending=False)

    return df_s, df_b

df_skills_raw, df_b = load_data()

# ==========================================
# 5. HEADER & REGION SELECTOR
# ==========================================
col_hdr, col_reg = st.columns([1.1, 1.3])
with col_hdr:
    st.markdown('<div class="app-header">📡 Market Radar</div>', unsafe_allow_html=True)

with col_reg:
    selected_region = st.selectbox(
        "Select Region",
        ["All Regions", "Europe", "US", "APAC"],
        label_visibility="collapsed"
    )

# Фільтрація за вибраним регіоном
df_filtered = df_skills_raw.copy()
if not df_filtered.empty and "region" in df_filtered.columns:
    if selected_region != "All Regions":
        df_filtered = df_filtered[df_filtered["region"] == selected_region]

# Розрахунок динамічних метрик
if not df_filtered.empty:
    agg_totals = (
        df_filtered.groupby("skill_name")["vacancy_count"]
        .sum()
        .reset_index()
        .sort_values(by="vacancy_count", ascending=False)
    )
    total_signals = int(agg_totals["vacancy_count"].sum())
    
    # Лідер №1 (Dominant Core)
    top_core_name = agg_totals.iloc[0]["skill_name"] if not agg_totals.empty else "N/A"
    top_core_count = int(agg_totals.iloc[0]["vacancy_count"]) if not agg_totals.empty else 0
    top_core_pct = int((top_core_count / total_signals * 100)) if total_signals > 0 else 0
    
    # Лідер №2 (Velocity Breakout)
    if len(agg_totals) > 1:
        breakout_name = str(agg_totals.iloc[1]["skill_name"])
        breakout_cnt = int(agg_totals.iloc[1]["vacancy_count"])
        breakout_badge = f"+{breakout_cnt} signals"
    else:
        breakout_name = top_core_name
        breakout_badge = "High Demand"
else:
    total_signals = 0
    top_core_name = "N/A"
    top_core_pct = 0
    breakout_name = "N/A"
    breakout_badge = "Steady"

# ==========================================
# 6. STATUS BAR (2x2 GRID З ДИНАМІЧНИМИ ДАНИМИ)
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
      <span class="status-value">{breakout_name} <span class="badge-green">⚡ {breakout_badge}</span></span>
    </div>
    <div class="status-col">
      <span class="status-label">Indexed Signals</span>
      <span class="status-value">{total_signals}</span>
    </div>
    <div class="status-col">
      <span class="status-label">Feed Status</span>
      <span class="status-value"><span style="color:#16a34a;">●</span> Live <span style="font-size:0.75rem; color:#64748b; font-weight:500;">(+{total_signals})</span></span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 7. TABS & DEMAND VELOCITY CHART
# ==========================================
tab_vel, tab_comp = st.tabs(["🔥 Demand Velocity", "💰"])

with tab_vel:
    if not df_filtered.empty:
        agg_chart = (
            df_filtered.groupby("skill_name", as_index=False)["vacancy_count"]
            .sum()
            .sort_values(by="vacancy_count", ascending=True)
            .tail(8)
        )
    else:
        agg_chart = pd.DataFrame(columns=["skill_name", "vacancy_count"])

    chart_height = max(240, len(agg_chart) * 28 + 30)

    fig = px.bar(
        agg_chart,
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
    st.caption("Compensation models based on verified APAC / Europe / US bands.")

# ==========================================
# 8. FRONTIER AI AUTONOMY (SAI) CARD (ДИНАМІЧНИЙ)
# ==========================================
if not df_b.empty and "sai_score" in df_b.columns:
    leader_row = df_b.iloc[0]
    leader_model = str(leader_row.get("model_name", "Gemini 2.5 Pro"))
    sai_val = float(leader_row.get("sai_score", 18.6))
else:
    sai_val = 18.6
    leader_model = "Gemini 2.5 Pro"

bar_width = min(max(sai_val, 0.0), 100.0)

st.markdown(f"""
<div class="sai-card">
  <div class="sai-header">
    <div class="sai-title">
      <span>⚙️ Frontier AI Autonomy (SAI)</span>
    </div>
    <div class="sai-score">{sai_val} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
  </div>
  <div class="sai-progress-bg">
    <div class="sai-progress-fill" style="width: {bar_width}%;"></div>
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

if not df_b.empty and "sai_score" in df_b.columns:
    with st.expander("📊 Compare Frontier Models (SAI Leaderboard)"):
        cols_to_show = [c for c in ["model_name", "organization", "sai_score", "arena_elo", "coding_score"] if c in df_b.columns]
        st.dataframe(
            df_b[cols_to_show].rename(
                columns={
                    "model_name": "Model",
                    "organization": "Org",
                    "sai_score": "SAI Score (/100)",
                    "arena_elo": "Arena Elo",
                    "coding_score": "Coding %"
                }
            ),
            use_container_width=True,
            hide_index=True
        )
