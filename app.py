import os
import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client

# ==========================================
# 1. PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Radar | Tech & AI Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==========================================
# 2. RESPONSIVE HIGH-CONTRAST CSS
# ==========================================
RESPONSIVE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif !important;
    background-color: #f8fafc !important;
    color: #0f172a !important;
}

[data-testid="stSidebar"] {
    background-color: #ffffff !important;
    border-right: 1px solid #cbd5e1 !important;
}

div[data-testid="stMetric"] {
    background: #ffffff !important;
    padding: 14px 16px !important;
    border-radius: 12px !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
    min-width: 100% !important;
}

div[data-testid="stMetricLabel"] p, div[data-testid="stMetricLabel"] span {
    font-size: 0.78rem !important;
    font-weight: 700 !important;
    color: #475569 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.03em !important;
}

div[data-testid="stMetricValue"] div {
    font-size: 1.45rem !important;
    font-weight: 800 !important;
    color: #0f172a !important;
}

div[data-testid="stPlotlyChart"] {
    background: #ffffff !important;
    border-radius: 12px !important;
    padding: 10px !important;
    border: 1px solid #cbd5e1 !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    background-color: #e2e8f0 !important;
    padding: 4px !important;
    border-radius: 10px !important;
    overflow-x: auto !important;
    white-space: nowrap !important;
}

.stTabs [data-baseweb="tab"] {
    height: 36px !important;
    border-radius: 8px !important;
    padding: 6px 14px !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: #334155 !important;
}

.stTabs [aria-selected="true"] {
    background-color: #ffffff !important;
    color: #0284c7 !important;
    font-weight: 700 !important;
}

@media (max-width: 768px) {
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.6rem !important;
        padding-right: 0.6rem !important;
    }
    div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 8px !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        flex: 1 1 calc(50% - 6px) !important;
        min-width: calc(50% - 6px) !important;
    }
    div[data-testid="stMetric"] {
        padding: 10px 12px !important;
    }
    div[data-testid="stMetricValue"] div {
        font-size: 1.25rem !important;
    }
}
</style>
"""
st.markdown(RESPONSIVE_CSS, unsafe_allow_html=True)

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
# 4. DATA LOADERS
# ==========================================
@st.cache_data(ttl=120)
def load_vacancies_data():
    res = supabase.table("fct_vacancies").select(
        "id, title, company, region, country_code, track, experience_level, source, posted_at"
    ).execute()
    return pd.DataFrame(res.data)

@st.cache_data(ttl=120)
def load_skills_data():
    res = supabase.table("bridge_vacancy_skills").select(
        "vacancy_id, dim_skills(canonical_name, category)"
    ).execute()
    records = []
    for r in res.data:
        if r.get("dim_skills"):
            records.append({
                "vacancy_id": r["vacancy_id"],
                "skill_name": r["dim_skills"]["canonical_name"],
                "skill_category": r["dim_skills"]["category"]
            })
    return pd.DataFrame(records)

@st.cache_data(ttl=120)
def load_ai_benchmarks():
    res = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
    df = pd.DataFrame(res.data)
    if not df.empty and "model_name" in df.columns:
        df = df[df["model_name"] != "Gemini 2.5 Flash"].copy()
        elo_norm = ((df["arena_elo"] - 1000.0) / (1400.0 - 1000.0) * 100.0).clip(0, 100)
        defense = (df["coding_score"] * 0.5 + df["hard_prompts_score"] * 0.5)
        raw_test_score = (0.35 * df["hard_prompts_score"] + 0.30 * df["coding_score"] + 0.20 * defense + 0.15 * elo_norm)
        df["skynet_index"] = (raw_test_score * 0.21).round(1)
    return df

df_vacancies = load_vacancies_data()
df_skills = load_skills_data()
df_benchmarks = load_ai_benchmarks()

# Merge vacancies with their skills
if not df_vacancies.empty and not df_skills.empty:
    df_merged = pd.merge(df_skills, df_vacancies, left_on="vacancy_id", right_on="id", how="inner")
else:
    df_merged = pd.DataFrame()

# ==========================================
# 5. SIDEBAR CONTROLS
# ==========================================
with st.sidebar:
    st.markdown("### 📡 Radar Controls")

    # Регіональний фільтр (APAC / EMEA)
    regions = ["All Regions"]
    if not df_vacancies.empty and "region" in df_vacancies.columns:
        regions += sorted(list(df_vacancies["region"].dropna().unique()))
    selected_region = st.selectbox("Region", regions)

    # Фільтр компаній (DeepSeek тощо)
    companies = ["All Companies"]
    if not df_vacancies.empty and "company" in df_vacancies.columns:
        companies += sorted(list(df_vacancies["company"].dropna().unique()))
    selected_company = st.selectbox("Company", companies)

    tracks = ["All Tracks"]
    if not df_vacancies.empty and "track" in df_vacancies.columns:
        tracks += sorted(list(df_vacancies["track"].dropna().unique()))
    selected_track = st.selectbox("Track", tracks)

    top_n = st.slider("Top Skills Count", min_value=5, max_value=25, value=10)

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ==========================================
# 6. HEADER & METRIC CARDS (2x2)
# ==========================================
st.markdown("### Market Intelligence Radar")
st.caption("Autonomous telemetry tracking global engineering demand, DeepSeek APAC lab openings, and AI autonomy.")

total_jobs = len(df_vacancies) if not df_vacancies.empty else 0
cn_jobs = len(df_vacancies[df_vacancies["country_code"] == "CN"]) if not df_vacancies.empty and "country_code" in df_vacancies.columns else 0
total_skills = len(df_skills) if not df_skills.empty else 0
top_sai = f"{df_benchmarks['skynet_index'].iloc[0]} / 100" if not df_benchmarks.empty and "skynet_index" in df_benchmarks.columns else "N/A"

col1, col2, col3, col4 = st.columns(4)
col1.metric("Indexed Jobs", f"{total_jobs}")
col2.metric("China / Frontier Lab", f"{cn_jobs}")
col3.metric("Extracted Skills", f"{total_skills}")
col4.metric("Autonomy Leader", top_sai)

st.write("")

# Helper for layout
def apply_chart_theme(fig):
    fig.update_layout(
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#0f172a", size=11),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(showgrid=True, gridcolor="#e2e8f0", tickfont=dict(color="#334155", size=10)),
        yaxis=dict(showgrid=False, tickfont=dict(color="#0f172a", size=11)),
        showlegend=False
    )
    return fig

# ==========================================
# 7. TABS
# ==========================================
tab1, tab2, tab3 = st.tabs(["🔥 Tech Demand", "🇨🇳 DeepSeek / China Lab", "🤖 AI Autonomy"])

with tab1:
    st.subheader("Global Engineering Tech Stack")
    filtered = df_merged.copy()
    if selected_region != "All Regions" and not filtered.empty:
        filtered = filtered[filtered["region"] == selected_region]
    if selected_company != "All Companies" and not filtered.empty:
        filtered = filtered[filtered["company"] == selected_company]
    if selected_track != "All Tracks" and not filtered.empty:
        filtered = filtered[filtered["track"] == selected_track]

    if not filtered.empty:
        agg = (
            filtered.groupby(["skill_name", "skill_category"], as_index=False)["vacancy_id"]
            .count()
            .rename(columns={"vacancy_id": "count"})
            .sort_values(by="count", ascending=True)
            .tail(top_n)
        )
        fig_skills = px.bar(
            agg, x="count", y="skill_name", orientation="h", text="count",
            color_discrete_sequence=["#0284c7"],
            labels={"count": "Mentions", "skill_name": "Technology"}
        )
        fig_skills = apply_chart_theme(fig_skills)
        fig_skills.update_traces(textposition="inside", insidetextfont=dict(color="#ffffff", size=11))
        st.plotly_chart(fig_skills, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
    else:
        st.info("No skill data matching selected filters.")

with tab2:
    st.subheader("DeepSeek / High-Flyer Lab Telemetry")
    if not df_vacancies.empty:
        ds_jobs = df_vacancies[df_vacancies["source"] == "deepseek_careers"]
        if not ds_jobs.empty:
            st.dataframe(
                ds_jobs[["title", "company", "country_code", "track", "experience_level"]],
                use_container_width=True,
                hide_index=True
            )

            # Навички безпосередньо DeepSeek
            ds_ids = ds_jobs["id"].tolist()
            ds_skills = df_skills[df_skills["vacancy_id"].isin(ds_ids)]
            if not ds_skills.empty:
                st.markdown("**Core Frontier Stack Detected:**")
                st.write(", ".join([f"`{s}`" for s in ds_skills["skill_name"].unique()]))
        else:
            st.info("No DeepSeek openings found.")
    else:
        st.info("No job records.")

with tab3:
    st.subheader("Frontier AI Autonomy Index (SAI)")
    if not df_benchmarks.empty:
        fig_ai = px.bar(
            df_benchmarks.sort_values(by="skynet_index", ascending=True),
            x="skynet_index", y="model_name", orientation="h", text="skynet_index",
            color_discrete_sequence=["#4f46e5"],
            labels={"skynet_index": "SAI Score (/100)", "model_name": "Model"}
        )
        fig_ai = apply_chart_theme(fig_ai)
        fig_ai.update_traces(textposition="inside", insidetextfont=dict(color="#ffffff", size=11))
        fig_ai.update_xaxes(range=[0, 100])
        st.plotly_chart(fig_ai, use_container_width=True, config={'responsive': True, 'displayModeBar': False})
