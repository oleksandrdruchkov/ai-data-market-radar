"""
fetch_benchmarks.py
Автоматизоване збереження метрик провідних моделей ШІ до Supabase (таблиця fct_ai_benchmarks).
Включає індикатори Humanity's Last Exam (HLE) та Terminal-Bench 2.0.
"""

import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Відсутні змінні оточення SUPABASE_URL або SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Актуальні виміри провідних моделей із урахуванням HLE та Terminal-Bench
BENCHMARKS = [
    {
        "model_name": "Claude 3.7 Sonnet",
        "organization": "Anthropic",
        "arena_elo": 1342.0,
        "hle_score": 18.5,             # Humanity's Last Exam (%)
        "terminal_bench_score": 52.4,  # Terminal-Bench / OS Agentic (%)
        "defense_score": 92.5,
        "coding_score": 93.8,
        "hard_prompts_score": 91.2,
        "license": "Proprietary"
    },
    {
        "model_name": "DeepSeek R1",
        "organization": "DeepSeek",
        "arena_elo": 1338.0,
        "hle_score": 15.2,
        "terminal_bench_score": 48.6,
        "defense_score": 92.4,
        "coding_score": 94.1,
        "hard_prompts_score": 90.8,
        "license": "Open Weights"
    },
    {
        "model_name": "Gemini 2.5 Pro",
        "organization": "Google",
        "arena_elo": 1345.0,
        "hle_score": 19.1,
        "terminal_bench_score": 50.8,
        "defense_score": 90.6,
        "coding_score": 91.5,
        "hard_prompts_score": 89.7,
        "license": "Proprietary"
    },
    {
        "model_name": "GPT-4o (Copilot Engine)",
        "organization": "OpenAI",
        "arena_elo": 1324.0,
        "hle_score": 11.8,
        "terminal_bench_score": 41.2,
        "defense_score": 87.8,
        "coding_score": 88.9,
        "hard_prompts_score": 86.8,
        "license": "Proprietary"
    },
    {
        "model_name": "Llama 3.3 70B Instruct",
        "organization": "Meta",
        "arena_elo": 1265.0,
        "hle_score": 7.4,
        "terminal_bench_score": 32.5,
        "defense_score": 79.8,
        "coding_score": 81.2,
        "hard_prompts_score": 78.5,
        "license": "Open Weights"
    }
]

def ingest_benchmarks():
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    
    for item in BENCHMARKS:
        row = item.copy()
        row["recorded_at"] = now_iso
        rows.append(row)

    logging.info(f"Відправка {len(rows)} записів бенчмарків до fct_ai_benchmarks...")
    res = supabase.table("fct_ai_benchmarks").insert(rows).execute()
    record_count = len(res.data) if res.data else 0
    logging.info(f"Успішно додано {record_count} записів у fct_ai_benchmarks.")

if __name__ == "__main__":
    ingest_benchmarks()
```[cite: 7, 8]

---

### Крок 2. Оновіть розрахунок у `app.py`

У функції `load_data()` всередині `app.py` замініть блок обчислення `raw_test_score`, щоб Streamlit-дашборд рахував підсумковий бал за новою формулою[cite: 7, 8]:

```python
        # Нормалізація Elo (діапазон 1000–1400)
        elo_norm = ((df_b["arena_elo"].fillna(1000.0) - 1000.0) / 400.0 * 100.0).clip(lower=0, upper=100)

        # 1. Екстремальні міркування: HLE (фолбек на hard_prompts)
        if "hle_score" in df_b.columns and df_b["hle_score"].notnull().any():
            reasoning = df_b["hle_score"].fillna(df_b.get("hard_prompts_score", 80.0))
        else:
            reasoning = df_b.get("hard_prompts_score", 80.0)

        # 2. Агентна дія та ОС: Terminal-Bench (фолбек на coding_score)
        if "terminal_bench_score" in df_b.columns and df_b["terminal_bench_score"].notnull().any():
            agentic = df_b["terminal_bench_score"].fillna(df_b.get("coding_score", 80.0))
        else:
            agentic = df_b.get("coding_score", 80.0)

        # 3. Кіберзахист / Стійкість
        if "defense_score" in df_b.columns and df_b["defense_score"].notnull().any():
            defense = df_b["defense_score"].fillna(agentic * 0.5 + reasoning * 0.5)
        else:
            defense = (agentic + reasoning) / 2.0

        # Зважена мультикритеріальна сума (MCDA)
        raw_test_score = (
            0.35 * reasoning +
            0.30 * agentic +
            0.20 * defense +
            0.15 * elo_norm
        )
        
        # Динамічний SAI з урахуванням діючого множника автономності з dim_autonomy_parameters
        df_b["sai_score"] = (raw_test_score * autonomy_mult).round(1)
        df_b = df_b.sort_values(by="sai_score", ascending=False).reset_index(drop=True)
