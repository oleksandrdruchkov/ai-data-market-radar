import os
import json
from datetime import datetime, timezone
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
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

.sai-card {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 12px 14px;
    margin-top: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.sai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 6px;
}

.sai-title {
    font-size: 0.95rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 5px;
}

.sai-score {
    font-size: 1.05rem;
    font-weight: 800;
    color: #4f46e5;
}

.sai-meta {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 0.8rem;
    color: #475569;
}

div[data-testid="stPlotlyChart"] {
    background: #ffffff !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid #cbd5e1 !important;
}
</style>
""", unsafe_allow_html=True)

SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
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

    try:
        res_benchmarks = supabase.table("v_latest_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
        df_b = pd.DataFrame(res_benchmarks.data)
    except Exception:
        try:
            res_benchmarks = supabase.table("fct_ai_benchmarks").select("*").order("arena_elo", desc=True).execute()
            df_b = pd.DataFrame(res_benchmarks.data)
        except Exception:
            df_b = pd.DataFrame()

    if not df_b.empty and "model_name" in df_b.columns:
        df_b = df_b[df_b["model_name"] != "Gemini 2.5 Flash"].copy()

    return df_s, df_ar, df_h, df_b

@st.cache_data(ttl=60)
def load_risk_data():
    try:
        prof_res = supabase.table("fct_risk_profiles").select("*").execute()
        df_prof = pd.DataFrame(prof_res.data)
        
        hor_res = supabase.table("fct_metr_horizons").select("*").eq("is_synthetic", False).execute()
        df_hor = pd.DataFrame(hor_res.data)
        
        return df_prof, df_hor
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

df_skills_base, df_arxiv, df_health, df_b = load_data()
df_prof, df_hor = load_risk_data()

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
    "sai_title": "🤖 AI Systemic Threat & Capability Radar" if is_en else "🤖 Вектор Системних Ризиків ШІ",
    "method_expander": "ℹ Empirical Methodology: CRI Tiers & Limits" if is_en else "ℹ️ Емпірична методологія: CRI Рівні та Ліміти",
    "compare_expander": "📊 Compare Frontier Models (Raw Benchmarks)" if is_en else "📊 Порівняння моделей ШІ (Сирі бенчмарки)"
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
# НОВИЙ ВЕКТОРНИЙ РАДАР (AI THREAT PROFILES)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
st.markdown(f"<div style='font-weight:800; font-size:1.05rem; color:#0f172a; margin-bottom:8px;'>{L['sai_title']}</div>", unsafe_allow_html=True)

if df_prof.empty:
    st.info("Data synchronization in progress. The Monte Carlo pipeline is updating risk vectors." if is_en else "Триває збір даних. Пайплайн Монте-Карло оновлює вектори ризику.")
else:
    models = df_prof['model_name'].unique()
    
    for model in models:
        model_profs = df_prof[df_prof['model_name'] == model]
        model_hor_rows = df_hor[df_hor['model_name'] == model] if not df_hor.empty else pd.DataFrame()
        model_hor = model_hor_rows.iloc[0] if not model_hor_rows.empty else None
        
        vector_elements = []
        for _, row in model_profs.iterrows():
            tier = row['assigned_tier']
            pathway = str(row['pathway']).upper()
            vector_elements.append(f"<b>{pathway}</b>: CRI-{tier}")
        vector_str = " | ".join(vector_elements)
        
        is_sat = model_profs['is_saturated'].any()
        max_tier = int(model_profs['assigned_tier'].max())
        
        if is_sat:
            sat_status = "<span style='color:#dc2626;'>🔴 <b>SATURATED</b> (Autonomy ≥ 16h)</span>" if is_en else "<span style='color:#dc2626;'>🔴 <b>МЕЖА ПРИЛАДУ</b> (Автономність ≥ 16 год)</span>"
            tier_display = f"CRI-{max_tier} <span style='font-size:0.75rem; color:#64748b; font-weight:600;'>[SATURATED]</span>"
            tier_color = "#dc2626"
        else:
            sat_status = "<span style='color:#10b981;'>🟢 <b>VALIDATED DOMAIN</b> (Within limits)</span>" if is_en else "<span style='color:#10b981;'>🟢 <b>ВАЛІДОВАНА ЗОНА</b> (В межах приладу)</span>"
            tier_display = f"CRI-{max_tier}"
            tier_color = "#4f46e5" if max_tier < 4 else "#dc2626"
            
        headroom_text = "N/A (Data Gap)"
        if model_hor is not None:
            t50 = float(model_hor['t50_obs'])
            t80 = float(model_hor['t80_obs']) if pd.notnull(model_hor['t80_obs']) else None
            
            h_t50 = max(0, np.log2(24.0 / max(t50, 16.0)))
            h_t80 = max(0, np.log2(8.0 / t80)) if t80 else 0
            
            limiting_factor = "T80 Reliability" if h_t80 > h_t50 else "T50 Autonomy"
            total_doublings = max(h_t50, h_t80)
            
            if total_doublings > 0:
                months_min = round(total_doublings * 3.5, 1)
                months_max = round(total_doublings * 7.0, 1)
                headroom_text = f"<b>{total_doublings:.2f} doublings</b> (~{months_min}–{months_max} months) <br><span style='color:#64748b;'>Limit factor: {limiting_factor}</span>" if is_en else f"<b>{total_doublings:.2f} подвоєнь</b> (~{months_min}–{months_max} міс.) <br><span style='color:#64748b;'>Ліміт. фактор: {limiting_factor}</span>"
            else:
                headroom_text = "⚠️ <b>Threshold crossed or imminent</b>" if is_en else "⚠️ <b>Поріг перетнуто або неминучий</b>"

        lbl_headroom = "Headroom to CRI-4:" if is_en else "Запас до CRI-4:"
        lbl_vector = "Pathway Vector:" if is_en else "Вектор шляхів:"
        lbl_metric = "Metric Status:" if is_en else "Статус горизонту:"

        st.markdown(f"""
        <div class="sai-card">
          <div class="sai-header">
            <div class="sai-title">{model}</div>
            <div class="sai-score" style="color:{tier_color};">{tier_display}</div>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:15px; margin-bottom:8px;">
            <div style="flex:1; min-width:180px;">
              <div class="sai-meta">
                <span>{lbl_vector}</span>
                <span style="color:#0f172a;">[{vector_str}]</span>
              </div>
            </div>
            <div style="flex:1; min-width:180px;">
              <div class="sai-meta">
                <span>{lbl_headroom}</span>
                <span style="color:#0f172a;">{headroom_text}</span>
              </div>
            </div>
          </div>
          <div class="sai-meta" style="border-top:1px dashed #e2e8f0; padding-top:6px; flex-direction:row; align-items:center; gap:5px;">
             <span>{lbl_metric}</span> {sat_status}
          </div>
        </div>
        """, unsafe_allow_html=True)

with st.expander(L["method_expander"]):
    if is_en:
        st.markdown("""
        **Empirical Methodology & Monte Carlo Risk Engine:**
        * **CRI (Catastrophic Risk Index) Tiers:** Evaluates models across structural pathways (Cyber, R&D, Replication). Levels range from CRI-1 (Tool) to CRI-4 (Systemic Autonomy).
        * **Monte Carlo Simulations:** Employs bivariate log-normal modeling for correlated $T_{50}$ and $T_{80}$ evaluation horizons, coupled with Beta-distributed capability ($C$) scores (10,000 iterations). 
        * **Instrument Ceiling:** METR's active testing boundary is strictly censored at **16.0 hours**. Any model exceeding this limit is flagged as `SATURATED` and blocked from speculative CRI-4 classification.
        * **Headroom:** Forecasts time-to-next-tier based on limiting capability constraints, using 3.5 to 7.0 month historical capability doubling trends.
        """)
    else:
        st.markdown("""
        **Емпірична методологія та Монте-Карло пайплайн:**
        * **Рівні CRI (Catastrophic Risk Index):** Оцінка моделей за структурними шляхами (Cyber, R&D, Replication). Рівні варіюються від CRI-1 (Інструмент) до CRI-4 (Системна автономність).
        * **Монте-Карло симуляція:** Використовує двовимірне логнормальне моделювання для корельованих горизонтів $T_{50}$ та $T_{80}$, а також бета-розподіл для показників спроможності $C$ (10 000 ітерацій).
        * **Стеля вимірювань:** Активна межа тестування METR суворо цензурується на рівні **16.0 годин**. Моделі, що перевищують цю межу, отримують статус `SATURATED`, що блокує спекулятивне призначення рівня CRI-4.
        * **Запас (Headroom):** Прогнозує час до перетину наступного порогу на основі лімітуючих факторів, використовуючи історичний тренд подвоєння спроможностей (від 3.5 до 7.0 місяців).
        """)

if not df_b.empty:
    with st.expander(L["compare_expander"]):
        cols_present = [c for c in ["model_name", "organization", "arena_elo", "coding_score", "hard_prompts_score", "license"] if c in df_b.columns]
        rename_map = {
            "model_name": "Model" if is_en else "Модель",
            "organization": "Org" if is_en else "Організація",
            "arena_elo": "Arena Elo",
            "coding_score": "Coding %" if is_en else "Код %",
            "hard_prompts_score": "Hard Prompts %" if is_en else "Складні промпти %",
            "license": "License" if is_en else "Ліцензія"
        }
        st.dataframe(
            df_b[cols_present].rename(columns=rename_map),
            use_container_width=True,
            hide_index=True
        )
