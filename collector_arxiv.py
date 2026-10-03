"""
collector_arxiv.py
Збір свіжих наукових публікацій з ArXiv (cs.AI, cs.CL, cs.LG)
та виявлення випереджальних навичок/професій через Gemini Flash.
"""

import os
import json
import logging
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timezone
from supabase import create_client, Client
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://npwqiyzmhjypfvrjssxi.supabase.co").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY or not GEMINI_API_KEY:
    raise ValueError("Відсутні змінні SUPABASE_URL, SUPABASE_KEY або GEMINI_API_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

ARXIV_API_URL = "https://export.arxiv.org/api/query"

def fetch_arxiv_papers(max_results=10):
    # Шукаємо останні роботи за напрямами AI, NLP та ML
    params = {
        "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results
    }
    
    response = requests.get(ARXIV_API_URL, params=params, timeout=20)
    response.raise_for_status()
    
    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    
    papers = []
    for entry in root.findall("atom:entry", ns):
        arxiv_id = entry.find("atom:id", ns).text.strip().split("/abs/")[-1]
        title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
        summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
        published = entry.find("atom:published", ns).text[:10]
        category = entry.find("atom:category", ns).attrib.get("term", "cs.AI")
        
        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "published_date": published,
            "category": category
        })
    return papers

def analyze_paper_trends(paper):
    prompt = f"""
    Проаналізуй науковий препринт з ШІ:
    Заголовок: {paper['title']}
    Анотація: {paper['summary']}

    Виділи головний практичний технологічний тренд для майбутнього ринку праці.
    Відповідай суворо у форматі валідного JSON:
    {{
        "predicted_skill": "коротка назва конкретного інструменту/підходу, наприклад: Test-Time Compute, GRPO, Agent Memory",
        "predicted_role": "прогнозована інженерна професія найближчих 6-12 місяців, наприклад: Reasoning Systems Engineer",
        "signal_summary": "1 лаконічне речення українською: чому це важливо для ринку"
    }}
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        return json.loads(response.text)
    except Exception as e:
        logging.warning(f"Помилка аналізу препринту {paper['arxiv_id']}: {e}")
        return None

def run_arxiv_pipeline():
    logging.info("Збір свіжих публікацій з ArXiv...")
    papers = fetch_arxiv_papers(max_results=8)
    logging.info(f"Отримано {len(papers)} робіт. Аналіз випереджальних навичок через Gemini...")
    
    records = []
    for p in papers:
        analysis = analyze_paper_trends(p)
        if analysis:
            records.append({
                "arxiv_id": p["arxiv_id"],
                "published_date": p["published_date"],
                "title": p["title"],
                "category": p["category"],
                "predicted_skill": analysis.get("predicted_skill"),
                "predicted_role": analysis.get("predicted_role"),
                "signal_summary": analysis.get("signal_summary")
            })
            
    if records:
        res = supabase.table("fct_arxiv_signals").upsert(records, on_conflict="arxiv_id").execute()
        logging.info(f"Успішно додано/оновлено {len(res.data) if res.data else 0} сигналів у fct_arxiv_signals.")

if __name__ == "__main__":
    run_arxiv_pipeline()
