import os
import json
import time
import hashlib
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Any

from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from supabase import create_client, Client

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FREE_TIER_DELAY_SECONDS = 13

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

ARXIV_AI_PROMPT = """
You are an AI Research Analyst.
Analyze the following scientific paper title and abstract from ArXiv (cs.AI, cs.LG, cs.CL).

Extract the core research signals and provide:
1. "summary_en": Concise English executive summary (max 2-3 sentences).
2. "summary_uk": Concise Ukrainian translation of the executive summary.
3. "primary_category": Main focus area (e.g. "LLM Reasoning", "Reinforcement Learning", "Model Compression", "Multimodal", "Robotics", "Systems/Kernel").
4. "key_innovations": List of 2-4 key breakthroughs or methods proposed.
5. "industry_impact": "High" | "Medium" | "Low" (assessing immediate applicability to industry).

Output strictly valid JSON:
{
  "summary_en": "...",
  "summary_uk": "...",
  "primary_category": "...",
  "key_innovations": ["...", "..."],
  "industry_impact": "High" | "Medium" | "Low"
}
"""

def calculate_content_hash(unique_str: str) -> str:
    return hashlib.sha256(unique_str.encode("utf-8")).hexdigest()

def fetch_arxiv_papers(search_query: str = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL", max_results: int = 8) -> List[Dict[str, Any]]:
    base_url = "http://export.arxiv.org/api/query?"
    params = f"search_query={urllib.parse.quote(search_query)}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    url = base_url + params

    logging.info(f"Збір свіжих публікацій з ArXiv (max {max_results})...")
    req = urllib.request.Request(url, headers={"User-Agent": "MarketRadarBot/1.0"})
    
    with urllib.request.urlopen(req) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    
    papers = []
    for entry in root.findall("atom:entry", namespace):
        raw_id = entry.find("atom:id", namespace).text.strip()
        # id має вигляд http://arxiv.org/abs/2610.08775v1 -> витягуємо номер
        paper_id = raw_id.split("/abs/")[-1]
        title = entry.find("atom:title", namespace).text.strip().replace("\n", " ")
        summary = entry.find("atom:summary", namespace).text.strip().replace("\n", " ")
        published = entry.find("atom:published", namespace).text.strip()
        
        authors = [a.find("atom:name", namespace).text.strip() for a in entry.findall("atom:author", namespace)]

        papers.append({
            "paper_id": paper_id,
            "title": title,
            "abstract": summary,
            "authors": authors,
            "published_at": published,
            "link": raw_id
        })

    return papers

def analyze_paper_with_gemini(paper: Dict[str, Any], max_retries: int = 5) -> Dict[str, Any]:
    prompt = f"{ARXIV_AI_PROMPT}\n\nTitle: {paper['title']}\n\nAbstract: {paper['abstract']}"
    gen_config = {
        "response_mime_type": "application/json",
        "thinking_level": "minimal"
    }

    for attempt in range(1, max_retries + 1):
        try:
            interaction = ai_client.interactions.create(
                model=MODEL_NAME,
                input=prompt,
                generation_config=gen_config
            )
            return json.loads(interaction.output_text)
        except (APIError, Exception) as err:
            err_str = str(err)
            is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
            is_server_busy = "503" in err_str or "UNAVAILABLE" in err_str

            if (is_rate_limit or is_server_busy) and attempt < max_retries:
                wait_time = 15 if is_rate_limit else (2 ** attempt * 5)
                logging.warning(
                    f"Gemini API [{MODEL_NAME}] помилка для {paper['paper_id']} ({err_str[:80]}...). "
                    f"Спроба {attempt}/{max_retries}. Очікування {wait_time}s..."
                )
                time.sleep(wait_time)
            else:
                raise err

def run_arxiv_pipeline():
    logging.info("=== START ARXIV INGESTION & ANALYSIS ===")
    papers = fetch_arxiv_papers(max_results=8)
    logging.info(f"Отримано {len(papers)} робіт. Двомовний аналіз через Gemini...")

    saved_count = 0

    for idx, paper in enumerate(papers):
        paper_id = paper["paper_id"]
        content_hash = calculate_content_hash(f"{paper['title']}|{paper['published_at']}")

        raw_payload = paper.copy()
        raw_record = {
            "job_id": paper_id,
            "source": "arxiv_research",
            "content_hash": content_hash,
            "payload": raw_payload,
            "status": "pending"
        }

        res = supabase.table("raw_jobs").upsert(
            [raw_record],
            on_conflict="content_hash,source"
        ).execute()

        raw_id = res.data[0]["id"] if res.data else None

        try:
            analysis = analyze_paper_with_gemini(paper)

            record_data = {
                "raw_job_id": raw_id,
                "external_id": paper_id,
                "source": "arxiv_research",
                "content_hash": content_hash,
                "title": paper["title"],
                "region": "GLOBAL",
                "country_code": "US",
                "track": analysis.get("primary_category", "AI Research"),
                "is_active": True,
                "posted_at": paper["published_at"],
                "metadata": {
                    "summary_en": analysis.get("summary_en"),
                    "summary_uk": analysis.get("summary_uk"),
                    "key_innovations": analysis.get("key_innovations", []),
                    "industry_impact": analysis.get("industry_impact", "Medium"),
                    "authors": paper.get("authors", []),
                    "link": paper.get("link")
                }
            }

            # Запис у таблицю фактів / вакансій або досліджень
            supabase.table("fct_vacancies").upsert(
                record_data,
                on_conflict="external_id,source"
            ).execute()

            if raw_id:
                supabase.table("raw_jobs").update({
                    "status": "processed",
                    "processed_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", raw_id).execute()

            saved_count += 1
            logging.info(f"Done [{saved_count}/{len(papers)}]: {paper_id} - {paper['title'][:50]}...")

        except Exception as e:
            logging.warning(f"Помилка аналізу {paper_id}: {e}")
            if raw_id:
                supabase.table("raw_jobs").update({"status": "failed"}).eq("id", raw_id).execute()

        # Обов'язкова затримка між ітераціями для квоти 5 запитів/хв
        if idx < len(papers) - 1:
            logging.info(f"Free Tier delay: очікування {FREE_TIER_DELAY_SECONDS}s перед наступною роботою...")
            time.sleep(FREE_TIER_DELAY_SECONDS)

    logging.info(f"=== FINISHED. Успішно опрацьовано: {saved_count}/{len(papers)} ===")

if __name__ == "__main__":
    run_arxiv_pipeline()
