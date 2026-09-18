import os
from datetime import datetime, timezone
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

BENCHMARK_DATA = [
    {"model_name": "Gemini 2.5 Pro", "organization": "Google", "arena_elo": 1340.0, "coding_score": 90.2, "hard_prompts_score": 88.5, "license": "Proprietary"},
    {"model_name": "Claude 3.7 Sonnet", "organization": "Anthropic", "arena_elo": 1335.0, "coding_score": 92.0, "hard_prompts_score": 89.1, "license": "Proprietary"},
    {"model_name": "GPT-4o", "organization": "OpenAI", "arena_elo": 1320.0, "coding_score": 88.4, "hard_prompts_score": 86.2, "license": "Proprietary"},
    {"model_name": "DeepSeek R1", "organization": "DeepSeek", "arena_elo": 1330.0, "coding_score": 93.5, "hard_prompts_score": 90.0, "license": "Open Weights"}
]

def ingest_benchmarks():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Missing Supabase credentials in environment variables.")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    now = datetime.now(timezone.utc).isoformat()
    rows = [{**item, "recorded_at": now} for item in BENCHMARK_DATA]
    supabase.table("fct_ai_benchmarks").insert(rows).execute()

if __name__ == "__main__":
    ingest_benchmarks()
