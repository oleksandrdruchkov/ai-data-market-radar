"""
collector_arxiv.py
Збір свіжих наукових публікацій з ArXiv (cs.AI, cs.CL, cs.LG)
та двомовна екстракція навичок/ролей через Gemini Flash з обробкою лімітів квот.
"""

import os
import json
import time
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

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Відсутні змінні SUPABASE_URL або SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

ARXIV_API_URL = "https://export.arxiv.org/api/query"


def fetch_arxiv_papers(max_results: int = 5):
    """Отримує останні статті з ArXiv із захистом від блокування 406."""
    params = {
        "search_query": "cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    headers = {
        "User-Agent": "MarketRadarBot/1.0 (https://github.com/oleksandrdruchkov/ai-data-market-radar; contact@marketradar.local)",
        "Accept": "application/atom+xml,application/xml,text/xml",
    }
    response = requests.get(ARXIV_API_URL, params=params, headers=headers, timeout=25)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    papers = []
    for entry in root.findall("atom:entry", ns):
        id_elem = entry.find("atom:id", ns)
        arxiv_id = (
            id_elem.text.strip().split("/abs/")[-1]
            if id_elem is not None
            else f"arxiv_{int(time.time())}"
        )

        title_elem = entry.find("atom:title", ns)
        title = (
            title_elem.text.strip().replace("\n", " ")
            if title_elem is not None
            else "Untitled"
        )

        summary_elem = entry.find("atom:summary", ns)
        summary = (
            summary_elem.text.strip().replace("\n", " ")
            if summary_elem is not None
            else ""
        )

        pub_elem = entry.find("atom:published", ns)
        published = pub_elem.text[:10] if pub_elem is not None else datetime.now(timezone.utc).strftime("%Y-%m-%d")

        cat_elem = entry.find("atom:category", ns)
        category = cat_elem.attrib.get("term", "cs.AI") if cat_elem is not None else "cs.AI"

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "published_date": published,
            "category": category,
        })
    return papers


def analyze_paper_trends(paper: dict) -> dict:
    """Аналізує статтю за допомогою моделі Gemini з Exponential Backoff та захистом від 429."""
    if not ai_client:
        return {
            "predicted_skill": "Emerging AI Architecture",
            "predicted_role_en": "AI Research Engineer",
            "predicted_role_ua": "Дослідник архітектур ШІ",
            "signal_summary_en": paper["title"][:150],
            "signal_summary_ua": paper["title"][:150],
        }

    prompt = f"""
    Analyze this AI research preprint:
    Title: {paper['title']}
    Abstract: {paper['summary']}

    Extract the emerging technology trend for the future tech job market.
    Respond strictly in valid JSON format:
    {{
        "predicted_skill": "global canonical name (e.g. GRPO, Test-Time Compute, Agent Memory)",
        "predicted_role_en": "predicted future job role in English",
        "predicted_role_ua": "predicted future job role in Ukrainian",
        "signal_summary_en": "1 concise sentence in English: why this is an important leading commercial indicator",
        "signal_summary_ua": "1 стисле речення українською: чому це важливо для майбутнього ринку"
    }}
    """

    # До 2 спроб із безпечною затримкою у разі 429
    max_retries = 2
    for attempt in range(max_retries):
        try:
            response = ai_client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            raw_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(raw_text)
        except Exception as e:
            err_msg = str(e)
            logging.warning(f"Спроба {attempt + 1}/{max_retries} для {paper['arxiv_id']} зазнала помилки: {err_msg}")
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                # Пауза для відновлення квоти Free Tier
                time.sleep(30)
            else:
                time.sleep(5)

    # Фолбек, щоб скрипт гарантовано не зависав і записав дані
    return {
        "predicted_skill": "Frontier AI Systems",
        "predicted_role_en": "AI Systems Engineer",
        "predicted_role_ua": "Інженер систем ШІ",
        "signal_summary_en": paper["title"][:150],
        "signal_summary_ua": paper["title"][:150],
    }


def run_arxiv_pipeline():
    logging.info("=== START ARXIV INGESTION & ANALYSIS ===")
    
    # 5 статей достатньо для регулярного нічного оновлення без перевищення добових і хвилинних квот
    papers = fetch_arxiv_papers(max_results=5)
    logging.info(f"Отримано {len(papers)} робіт. Починаємо обробку через Gemini...")

    records = []
    for idx, p in enumerate(papers):
        analysis = analyze_paper_trends(p)
        if analysis:
            summary_payload = {
                "en": analysis.get("signal_summary_en", ""),
                "ua": analysis.get("signal_summary_ua", ""),
                "role_en": analysis.get("predicted_role_en", ""),
                "role_ua": analysis.get("predicted_role_ua", ""),
            }
            records.append({
                "arxiv_id": p["arxiv_id"],
                "published_date": p["published_date"],
                "title": p["title"],
                "category": p["category"],
                "predicted_skill": analysis.get("predicted_skill"),
                "predicted_role": analysis.get("predicted_role_en"),
                "signal_summary": json.dumps(summary_payload, ensure_ascii=False),
            })

        # Пауза 13 секунд між викликами для дотримання ліміту Free Tier (5 запитів на хвилину)
        if idx < len(papers) - 1:
            time.sleep(13)

    if records:
        res = (
            supabase.table("fct_arxiv_signals")
            .upsert(records, on_conflict="arxiv_id")
            .execute()
        )
        saved_count = len(res.data) if res.data else len(records)
        logging.info(f"Успішно збережено/оновлено {saved_count} сигналів у fct_arxiv_signals.")
    else:
        logging.info("Немає нових записів для збереження.")


if __name__ == "__main__":
    run_arxiv_pipeline()
