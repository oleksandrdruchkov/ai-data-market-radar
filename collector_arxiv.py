import os
import json
import logging
import xml.etree.ElementTree as ET
import requests
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

def fetch_arxiv_papers(max_results=8):
    params = {
        "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results
    }
    headers = {
        "User-Agent": "MarketRadarBot/1.0 (https://github.com/oleksandrdruchkov/ai-data-market-radar; contact@marketradar.local)",
        "Accept": "application/atom+xml,application/xml,text/xml"
    }
    
    response = requests.get(ARXIV_API_URL, params=params, headers=headers, timeout=20)
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
    Analyze this AI preprint:
    Title: {paper['title']}
    Abstract: {paper['summary']}

    Extract the emerging technology trend for the future job market.
    Respond strictly in valid JSON format with bilingual entries:
    {{
        "predicted_skill": "global canonical name (e.g. GRPO, Test-Time Compute, Agent Scaffolding)",
        "predicted_role_en": "predicted role in English (e.g. Reasoning Systems Engineer)",
        "predicted_role_ua": "predicted role in Ukrainian (e.g. Інженер систем логічного виводу)",
        "signal_summary_en": "1 concise sentence in English: why this is a leading commercial indicator",
        "signal_summary_ua": "1 стисле речення українською: чому це важливо для майбутнього комерційного найму"
    }}
    """
    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        return json.loads(response.text)
    except Exception as e:
        logging.warning(f"Помилка аналізу {paper['arxiv_id']}: {e}")
        return None

def run_arxiv_pipeline():
    logging.info("Збір свіжих публікацій з ArXiv...")
    papers = fetch_arxiv_papers(max_results=8)
    logging.info(f"Отримано {len(papers)} робіт. Двомовний аналіз через Gemini...")
    
    records = []
    for p in papers:
        analysis = analyze_paper_trends(p)
        if analysis:
            summary_payload = {
                "en": analysis.get("signal_summary_en", ""),
                "ua": analysis.get("signal_summary_ua", ""),
                "role_en": analysis.get("predicted_role_en", ""),
                "role_ua": analysis.get("predicted_role_ua", "")
            }
            records.append({
                "arxiv_id": p["arxiv_id"],
                "published_date": p["published_date"],
                "title": p["title"],
                "category": p["category"],
                "predicted_skill": analysis.get("predicted_skill"),
                "predicted_role": analysis.get("predicted_role_en"),
                "signal_summary": json.dumps(summary_payload, ensure_ascii=False)
            })
            
    if records:
        res = supabase.table("fct_arxiv_signals").upsert(records, on_conflict="arxiv_id").execute()
        logging.info(f"Успішно збережено {len(res.data) if res.data else 0} сигналів у fct_arxiv_signals.")

if __name__ == "__main__":
    run_arxiv_pipeline()
