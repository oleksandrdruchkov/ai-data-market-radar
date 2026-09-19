import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def calculate_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def resolve_skill_id(skill_name: str, category: str) -> int:
    clean_name = skill_name.strip()
    res = supabase.table("dim_skills").select("skill_id").ilike("canonical_name", clean_name).execute()
    if res.data:
        return res.data[0]["skill_id"]

    created = supabase.table("dim_skills").upsert(
        {"canonical_name": clean_name, "category": category or "Tool"},
        on_conflict="canonical_name"
    ).execute()
    if created.data:
        return created.data[0]["skill_id"]

    res = supabase.table("dim_skills").select("skill_id").eq("canonical_name", clean_name).single().execute()
    return res.data["skill_id"]

def fetch_adzuna_jobs(country: str = "gb", results_per_page: int = 15) -> List[Dict[str, Any]]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logging.warning("Adzuna credentials not set, skipping API call.")
        return []
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": results_per_page,
        "what": "data engineer ai",
        "content-type": "application/json"
    }
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code == 200:
        return resp.json().get("results", [])
    logging.error(f"Adzuna API error {resp.status_code}: {resp.text}")
    return []

def run_main_pipeline():
    logging.info("=== START MAIN MARKET PIPELINE ===")
    jobs = fetch_adzuna_jobs()
    logging.info(f"Fetched {len(jobs)} jobs from Adzuna.")

    for item in jobs:
        ext_id = str(item.get("id"))
        title = item.get("title", "")
        desc = item.get("description", "")
        company = item.get("company", {}).get("display_name", "Unknown")
        location = item.get("location", {}).get("display_name", "")
        chash = calculate_content_hash(f"{title}|{company}|{desc}")

        raw_res = supabase.table("raw_jobs").upsert([{
            "job_id": ext_id,
            "source": "adzuna",
            "content_hash": chash,
            "payload": item,
            "status": "pending"
        }], on_conflict="content_hash,source").execute()

        raw_id = raw_res.data[0]["id"] if raw_res.data else None

        fct_res = supabase.table("fct_vacancies").upsert({
            "raw_job_id": raw_id,
            "external_id": ext_id,
            "source": "adzuna",
            "content_hash": chash,
            "region": "EMEA",
            "country_code": "GB",
            "title": title,
            "company": company,
            "location": location,
            "currency": "GBP",
            "salary_period": "yearly",
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "track": "Data Engineering",
            "is_active": True,
            "posted_at": item.get("created", datetime.now(timezone.utc).isoformat())
        }, on_conflict="external_id,source").execute()

        if raw_id:
            supabase.table("raw_jobs").update({
                "status": "processed",
                "processed_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", raw_id).execute()

    logging.info("=== MAIN MARKET PIPELINE COMPLETE ===")

if __name__ == "__main__":
    run_main_pipeline()
