import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client

# Завантажуємо локальний .env
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL", "[https://npwqiyzmhjypfvrjssxi.supabase.co](https://npwqiyzmhjypfvrjssxi.supabase.co)")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

DEEPSEEK_AI_PROMPT = """
You are an expert Data/AI recruiter and technical analyst specializing in frontier AI labs.
Analyze the following job description (which may be in Chinese or English) from DeepSeek / High-Flyer.
Translate Chinese technical roles and requirements into standard English industry terms.

Output strictly valid JSON conforming to this schema:
{
  "translated_title_en": "Standard English Title (e.g. CUDA Optimization Engineer, Reinforcement Learning Researcher)",
  "experience_level": "Junior" | "Mid" | "Senior" | "Lead/Staff" | "Not Specified",
  "work_model": "Remote" | "Hybrid" | "On-site" | "Not Specified",
  "track": "Machine Learning" | "Data Engineering" | "Backend" | "AI Alignment" | "Other",
  "skills": [
    {
      "name": "Canonical technology name in English (e.g. CUDA, PyTorch, Triton, vLLM, DeepSeek, GRPO, C++, Linux, Docker)",
      "category": "AI Hardware/Kernel" | "Post-training" | "Deep Learning Framework" | "Language" | "AI Serving" | "Applied AI" | "DevOps" | "Database" | "Tool"
    }
  ]
}
"""

def calculate_content_hash(unique_str: str) -> str:
    return hashlib.sha256(unique_str.encode("utf-8")).hexdigest()

def resolve_skill_id(skill_name: str, category: str) -> int:
    skill_clean = skill_name.strip()
    alias_res = supabase.table("dim_skill_aliases").select("skill_id").ilike("alias", skill_clean).execute()
    if alias_res.data:
        return alias_res.data[0]["skill_id"]

    skill_res = supabase.table("dim_skills").select("skill_id").ilike("canonical_name", skill_clean).execute()
    if skill_res.data:
        return skill_res.data[0]["skill_id"]

    new_skill = supabase.table("dim_skills").upsert(
        {"canonical_name": skill_clean, "category": category or "Tool"},
        on_conflict="canonical_name"
    ).execute()

    if new_skill.data:
        return new_skill.data[0]["skill_id"]

    res = supabase.table("dim_skills").select("skill_id").eq("canonical_name", skill_clean).single().execute()
    return res.data["skill_id"]

def fetch_deepseek_openings() -> List[Dict[str, Any]]:
    return [
        {
            "id": "ds-kernel-01",
            "title": "大模型底层算子/CUDA优化专家",
            "location": "Hangzhou, China / Beijing",
            "company": "DeepSeek",
            "description": "负责DeepSeek-V3/R1大规模分布式训练与推理的算子性能优化。精通CUDA、Triton、PTX底层汇编优化，深入理解DualPipe并行与MLA注意力机制内存压缩。熟练掌握PyTorch与C++，具备GPU显存瓶颈突破经验。"
        },
        {
            "id": "ds-rl-02",
            "title": "强化学习与推理算法研究员 (R1 Reasoning)",
            "location": "Beijing, China",
            "company": "DeepSeek",
            "description": "专注于大语言模型大规模强化学习(RL)与Long CoT推理能力探索。深入研究GRPO算法、Pure RL探索机制与自我反思验证。熟练运用Python, PyTorch, vLLM/SGLang分布式环境，具备数学/代码竞赛解题数据合成经验。"
        },
        {
            "id": "ds-infra-03",
            "title": "分布式AI基础设施与存储工程师",
            "location": "Hangzhou, China",
            "company": "DeepSeek",
            "description": "负责万卡集群高效存储与通信网络拓扑优化。熟练掌握RDMA, InfiniBand, Kubernetes, Docker, Ceph分布式文件系统，确保671B MoE模型训练时GPU利用率最大化。"
        }
    ]

def run_deepseek_pipeline():
    logging.info("=== START DEEPSEEK INGESTION & TRANSLATION ===")
    jobs = fetch_deepseek_openings()
    saved_count = 0

    for job in jobs:
        ext_id = str(job["id"])
        source_name = "deepseek_careers"
        content_hash = calculate_content_hash(f"{job['title']}|{job['company']}|{job['description']}")

        raw_payload = job.copy()
        raw_payload["_metadata"] = {
            "country_code": "cn",
            "region": "APAC",
            "currency": "CNY",
            "original_language": "zh"
        }

        raw_record = {
            "job_id": ext_id,
            "source": source_name,
            "content_hash": content_hash,
            "payload": raw_payload,
            "status": "pending"
        }

        res = supabase.table("raw_jobs").upsert(
            [raw_record],
            on_conflict="content_hash,source"
        ).execute()

        raw_id = res.data[0]["id"] if res.data else None

        logging.info(f"Translating and analyzing via Gemini: {job['title']}...")
        prompt = f"{DEEPSEEK_AI_PROMPT}\n\nTitle: {job['title']}\nDescription: {job['description']}"

        try:
            ai_res = ai_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            extracted = json.loads(ai_res.text)

            vacancy_data = {
                "raw_job_id": raw_id,
                "external_id": ext_id,
                "source": source_name,
                "content_hash": content_hash,
                "region": "APAC",
                "country_code": "CN",
                "title": extracted.get("translated_title_en", job["title"]),
                "company": "DeepSeek",
                "location": job.get("location", "Hangzhou, China"),
                "currency": "CNY",
                "salary_period": "yearly",
                "experience_level": extracted.get("experience_level", "Senior"),
                "work_model": extracted.get("work_model", "On-site"),
                "track": extracted.get("track", "Machine Learning"),
                "is_active": True,
                "posted_at": datetime.now(timezone.utc).isoformat()
            }

            fct_res = supabase.table("fct_vacancies").upsert(
                vacancy_data,
                on_conflict="external_id,source"
            ).execute()

            if fct_res.data:
                v_row = fct_res.data[0]
                vacancy_id = v_row.get("id") or v_row.get("vacancy_id")
                bridge_entries = []
                for s in extracted.get("skills", []):
                    s_name = s.get("name")
                    s_cat = s.get("category", "Tool")
                    if s_name:
                        s_id = resolve_skill_id(s_name, s_cat)
                        bridge_entries.append({"vacancy_id": vacancy_id, "skill_id": s_id})

                if bridge_entries:
                    supabase.table("bridge_vacancy_skills").upsert(bridge_entries).execute()

            if raw_id:
                supabase.table("raw_jobs").update({
                    "status": "processed",
                    "processed_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", raw_id).execute()

            saved_count += 1
            logging.info(f"Done: {extracted.get('translated_title_en')} | Skills: {len(extracted.get('skills', []))}")

        except Exception as e:
            logging.error(f"Error processing {ext_id}: {e}")
            if raw_id:
                supabase.table("raw_jobs").update({"status": "failed"}).eq("id", raw_id).execute()

    logging.info(f"=== FINISHED. Successfully processed: {saved_count} ===")

if __name__ == "__main__":
    run_deepseek_pipeline()
