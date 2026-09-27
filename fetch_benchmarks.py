"""
fetch_benchmarks.py
Автоматизоване збереження метрик провідних моделей ШІ до Supabase (таблиця fct_ai_benchmarks).
Скрипт використовує стандартний .insert(), сумісний зі структурою таблиці.
"""

import os
import logging
from datetime import datetime, timezone
from supabase import create_client, Client

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# 1. Зчитування ключів доступу
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Відсутні змінні оточення SUPABASE_URL або SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. Актуальний зріз бенчмарків топових моделей
BENCHMARKS = [
    {
        "model_name": "Claude 3.7 Sonnet",
        "organization": "Anthropic",
        "arena_elo": 1342.0,
        "coding_score": 93.8,
        "hard_prompts_score": 91.2,
        "defense_score": 92.5,
        "license": "Proprietary"
    },
    {
        "model_name": "DeepSeek R1",
        "organization": "DeepSeek",
        "arena_elo": 1338.0,
        "coding_score": 94.1,
        "hard_prompts_score": 90.8,
        "defense_score": 92.4,
        "license": "Open Weights"
    },
    {
        "model_name": "Gemini 2.5 Pro",
        "organization": "Google",
        "arena_elo": 1345.0,
        "coding_score": 91.5,
        "hard_prompts_score": 89.7,
        "defense_score": 90.6,
        "license": "Proprietary"
    },
    {
        "model_name": "GPT-4o (Copilot Engine)",
        "organization": "OpenAI",
        "arena_elo": 1324.0,
        "coding_score": 88.9,
        "hard_prompts_score": 86.8,
        "defense_score": 87.8,
        "license": "Proprietary"
    },
    {
        "model_name": "Llama 3.3 70B Instruct",
        "organization": "Meta",
        "arena_elo": 1265.0,
        "coding_score": 81.2,
        "hard_prompts_score": 78.5,
        "defense_score": 79.8,
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

    # Чистий insert без обмежень на конфлікти
    res = supabase.table("fct_ai_benchmarks").insert(rows).execute()

    record_count = len(res.data) if res.data else 0
    logging.info(f"Успішно збережено {record_count} записів у fct_ai_benchmarks.")

if __name__ == "__main__":
    ingest_benchmarks()
