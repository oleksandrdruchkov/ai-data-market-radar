import os
from datetime import datetime, timezone
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
# 2. MOBILE-FIRST RESPONSIVE CSS
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

/* КАРТКА SAI ВНИЗУ */
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
    align-items: flex-start;
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
    font-size: 1.25rem;
    font-weight: 800;
    color: #0284c7;
    text-align: right;
}

.sai-progress-bg {
    width: 100%;
    height: 7px;
    background-color: #e2e8f0;
    border-radius: 999px;
    overflow: hidden;
    margin: 8px 0;
}

.sai-progress-fill {
    height: 100%;
    background-color: #0284c7;
    border-radius: 999px;
}

.sai-footer {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    color: #475569;
}

/* ТАБИ ТА ПЛОТЛІ */
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
# 4. DATA LOADERS & DYNAMIC MULTIPLIER
# ==========================================
@st.cache_data(ttl=60)
def load_data():
    res_skills = supabase.table("v_skill_demand_stats").select("*").execute()
    res_benchmarks = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()

    # Завантаження динамічного множника автономності
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

    try:
        res_salaries = supabase.table("v_salary_by_role_market").select("*").execute()
        df_sal = pd.DataFrame(res_salaries.data)
    except Exception:
        df_sal = pd.DataFrame()

    df_s = pd.DataFrame(res_skills.data)
    df_b = pd.DataFrame(res_benchmarks.data)

    return df_s, df_b, df_sal, autonomy_mult, horizon_mins

@st.cache_data(ttl=60)
def load_sai_history():
    try:
        res = (
            supabase.table("v_sai_history")
            .select("*")
            .order("eval_date", desc=False)
            .execute()
        )
        return pd.DataFrame(res.data)
    except Exception:
        return pd.DataFrame()

df_skills_raw, df_b, df_salaries, active_multiplier, active_horizon = load_data()
df_sai_hist = load_sai_history()

# ==========================================
# 5. HEADER & REGIONAL SCOPE
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

# Фільтрація ринкових даних
df_filtered = df_skills_raw.copy()
if not df_filtered.empty and "region" in df_filtered.columns:
    if selected_region != "All Regions":
        df_filtered = df_filtered[df_filtered["region"] == selected_region]

# Розрахунок метрик активного ринку
if not df_filtered.empty:
    agg_totals = (
        df_filtered.groupby("skill_name")["vacancy_count"]
        .sum()
        .reset_index()
        .sort_values(by="vacancy_count", ascending=False)
    )
    total_signals = int(agg_totals["vacancy_count"].sum())

    top_core_name = str(agg_totals.iloc[0]["skill_name"]) if not agg_totals.empty else "N/A"
    top_core_count = int(agg_totals.iloc[0]["vacancy_count"]) if not agg_totals.empty else 0
    top_core_pct = int((top_core_count / total_signals * 100)) if total_signals > 0 else 0

    if len(agg_totals) > 1:
        breakout_name = str(agg_totals.iloc[1]["skill_name"])
        breakout_cnt = int(agg_totals.iloc[1]["vacancy_count"])
        breakout_badge = f"+{breakout_cnt} signals"
    else:
        breakout_name = top_core_name
        breakout_badge = "Dominant"
else:
    total_signals = 0
    top_core_name = "N/A"
    top_core_pct = 0
    breakout_name = "N/A"
    breakout_badge = "Steady"

# ==========================================
# 6. STATUS BAR (2x2 GRID)
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
      <span class="status-value"><span style="color:#16a34a;">●</span> Live <span style="font-size:0.75rem; color:#64748b; font-weight:500;">(+96)</span></span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ==========================================
# 7. TABS & CHARTS (DEMAND & SALARY)
# ==========================================
tab_vel, tab_comp = st.tabs(["🔥 Demand Velocity", "💰 Compensation"])

with tab_vel:
    if not df_filtered.empty:
        agg_chart = (
            df_filtered.groupby("skill_name")["vacancy_count"]
            .sum()
            .reset_index()
            .sort_values(by="vacancy_count", ascending=True)
            .tail(8)
        )
    else:
        agg_chart = pd.DataFrame({"skill_name": ["N/A"], "vacancy_count": [0]})

    chart_height = max(240, len(agg_chart) * 28 + 35)

    fig_demand = px.bar(
        agg_chart,
        x="vacancy_count",
        y="skill_name",
        orientation="h",
        text="vacancy_count",
        color_discrete_sequence=["#0284c7"]
    )
    fig_demand.update_layout(
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
    fig_demand.update_traces(
        textposition="inside",
        insidetextfont=dict(color="#ffffff", size=10),
        width=0.42
    )
    st.plotly_chart(fig_demand, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

with tab_comp:
    if not df_salaries.empty:
        df_sal_flt = df_salaries.copy()
        if selected_region != "All Regions" and "region" in df_sal_flt.columns:
            df_sal_flt = df_sal_flt[df_sal_flt["region"] == selected_region]

        if not df_sal_flt.empty:
            fig_sal = px.bar(
                df_sal_flt,
                x="track",
                y="median_salary_midpoint",
                color="region" if "region" in df_sal_flt.columns else None,
                barmode="group",
                title=f"Median Salary ($ USD) - {selected_region}"
            )
            fig_sal.update_layout(
                paper_bgcolor="#ffffff",
                plot_bgcolor="#ffffff",
                height=280,
                margin=dict(l=10, r=10, t=30, b=20),
                bargap=0.35,
                bargroupgap=0.15
            )
            st.plotly_chart(fig_sal, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
        else:
            st.caption(f"No salary records available for {selected_region}.")
    else:
        st.caption("Salary data pipeline currently compiling.")

# ==========================================
# 8. FRONTIER AI AUTONOMY (SAI) CARD & FRESHNESS AUDIT
# ==========================================
data_status_badge = ""
is_stale = False
last_date_str = "N/A"
has_real_defense = False

if not df_b.empty and "recorded_at" in df_b.columns:
    df_b["recorded_at_dt"] = pd.to_datetime(df_b["recorded_at"], utc=True)
    latest_ts = df_b["recorded_at_dt"].max()
    now_utc = datetime.now(timezone.utc)
    
    age_hours = (now_utc - latest_ts).total_seconds() / 3600.0
    last_date_str = latest_ts.strftime("%d.%m.%Y")

    if age_hours <= 48:
        data_status_badge = f'<span style="color:#10b981; font-size:0.75rem; font-weight:600;">● Fresh (зріз: {last_date_str})</span>'
    else:
        is_stale = True
        days_stale = int(age_hours // 24)
        data_status_badge = f'<span style="color:#f59e0b; font-size:0.75rem; font-weight:600;">⚠️ Stale ({days_stale} дн. тому, {last_date_str})</span>'
else:
    data_status_badge = '<span style="color:#ef4444; font-size:0.75rem; font-weight:600;">⚠️ Default Fallback</span>'

# Розрахунок індексу з перевіркою проксі кіберзахисту
if not df_b.empty:
    if "model_name" in df_b.columns and len(df_b) > 1:
        df_b = df_b[df_b["model_name"] != "Gemini 2.5 Flash"].copy()

    elo_norm = ((df_b["arena_elo"].fillna(1000.0) - 1000.0) / 400.0 * 100.0).clip(lower=0, upper=100)
    hard_p = df_b["hard_prompts_score"].fillna(80.0) if "hard_prompts_score" in df_b.columns else 80.0
    coding_s = df_b["coding_score"].fillna(80.0) if "coding_score" in df_b.columns else 80.0

    if "defense_score" in df_b.columns and df_b["defense_score"].notnull().any():
        defense = df_b["defense_score"].fillna((coding_s + hard_p) / 2.0)
        has_real_defense = True
    else:
        defense = (coding_s + hard_p) / 2.0

    raw_test_score = (
        0.35 * hard_p +
        0.30 * coding_s +
        0.20 * defense +
        0.15 * elo_norm
    )

    df_b["sai_score"] = (raw_test_score * active_multiplier).round(1)
    df_b = df_b.sort_values(by="sai_score", ascending=False).reset_index(drop=True)

    leader_row = df_b.iloc[0]
    leader_model = str(leader_row.get("model_name", "Claude 3.7 Sonnet"))
    sai_val = float(leader_row.get("sai_score", 19.2))
else:
    sai_val = 18.6
    leader_model = "Gemini 2.5 Pro (Fallback)"

bar_width = min(max(sai_val, 0.0), 100.0)
proxy_badge = "" if has_real_defense else ' <span style="font-size:0.7rem; color:#f59e0b;">(Defense: 50/50 Proxy)</span>'

st.markdown(f"""
<div class="sai-card">
  <div class="sai-header">
    <div>
      <div class="sai-title">🤖 Frontier AI Autonomy (SAI)</div>
      <div style="margin-top:2px;">{data_status_badge}</div>
    </div>
    <div class="sai-score">{sai_val} <span style="font-size:0.75rem; color:#64748b;">/ 100</span></div>
  </div>
  <div class="sai-progress-bg">
    <div class="sai-progress-fill" style="width: {bar_width}%;"></div>
  </div>
  <div class="sai-footer">
    <span>Leader: <b>{leader_model}</b>{proxy_badge}</span>
    <span style="color:#0284c7; font-weight:700;">ASL-2 (Safe Copilot)</span>
  </div>
</div>
""", unsafe_allow_html=True)

if is_stale:
    st.caption(f"ℹ️ **Зверніть увагу:** Нові виміри не надходили понад 48 годин. Розрахунок базується на збереженому зрізі від {last_date_str}.")

# ==========================================
# 9. EXPANDERS: TIMELINE, METHODOLOGY & LEADERBOARD
# ==========================================
# 1. Графік історії зміни SAI із чіткими вертикальними назвами моделей
if not df_sai_hist.empty and len(df_sai_hist) > 1:
    with st.expander("📈 Dynamic Timeline: Історія зміни індексу SAI"):
        fig_hist = px.line(
            df_sai_hist,
            x="eval_date",
            y="leader_sai",
            markers=True,
            title="Динаміка Frontier AI Autonomy (SAI Score)",
            labels={
                "eval_date": "Дата вимірювання",
                "leader_sai": "Індекс SAI (/100)"
            },
            hover_data={"leader_model": True, "leader_org": True, "current_multiplier": True}
        )
        fig_hist.update_traces(
            line_color="#0284c7",
            marker=dict(size=8, color="#0369a1")
        )
        
        # Створення вертикальних підписів (-90 градусів) над кожною точкою (білий контрастний шрифт)
        annotations = []
        for _, row in df_sai_hist.iterrows():
            annotations.append(dict(
                x=row["eval_date"],
                y=row["leader_sai"],
                text=str(row["leader_model"]),
                showarrow=False,
                yshift=50,
                textangle=-90,
                font=dict(size=10, color="#f8fafc", family="Inter, -apple-system, sans-serif")
            ))
            
        min_sai = max(0.0, float(df_sai_hist["leader_sai"].min()) - 2.0)
        max_sai = min(100.0, float(df_sai_hist["leader_sai"].max()) + 7.5)
        
        fig_hist.update_layout(
            annotations=annotations,
            yaxis_range=[min_sai, max_sai],
            margin=dict(l=20, r=20, t=95, b=20),
            height=410,
            dragmode="pan",
            xaxis=dict(rangeslider=dict(visible=True, thickness=0.08)),
            yaxis=dict(fixedrange=True, ticksuffix="%")
        )
        st.plotly_chart(fig_hist, use_container_width=True)

# 2. Блок методології
with st.expander("ℹ️ Data Sources & Autonomy Methodology (Джерела та формула)"):
    st.markdown(f"""
    **Відкриті джерела даних (Public Benchmarks):**
    * **General Alignment:** LMSYS Chatbot Arena (Elo Rating, нормалізований у діапазон 1000–1400).
    * **Software Engineering & Coding:** SWE-bench / HumanEval (% успішного виконання).
    * **Complex Reasoning:** Hard Prompts & Multi-step Evals.
    * **Cyber & Defensive Capabilities:** Проксі-оцінка аудиту коду (50/50 Code + Reasoning або Scale AI SEAL).

    **Математика зведення:**
    $$SAI = (0.35 \\cdot S_{{\\text{{Reasoning}}}} + 0.30 \\cdot S_{{\\text{{Coding}}}} + 0.20 \\cdot S_{{\\text{{Cyber}}}} + 0.15 \\cdot S_{{\\text{{General}}}}) \\times M_{{\\text{{Autonomy}}}}$$

    * **Активний множник автономності ($M_{{\\text{{Autonomy}}}} = {active_multiplier}$):** 
      Підтягується з таблиці `dim_autonomy_parameters`. Відповідає стійкому горизонту дій **~{int(active_horizon)} хв** без втручання людини.
    * **Рівень ризику:** **ASL-2 (Safe Copilot)** — інструмент під регулярним наглядом оператора.
    """)

# 3. Таблиця лідерборду
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
