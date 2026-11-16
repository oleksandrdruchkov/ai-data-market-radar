"""
collectors/_job_keywords.py
Розбір вакансії ключовими словами, без мовної моделі.

Навіщо: усі вакансії - китайських лабораторій і з Adzuna (США, Європа, Сингапур, Індія) -
розбираються однаково, відтворювано і без витрат квоти Gemini. Що слово означає - записано тут, у словнику; та сама
вакансія завжди дає той самий результат.

Що визначається:
  навички   назви технологій і методів зі словника SKILLS (латинські назви + китайські відповідники);
            лише для технічних посад: вакансія з напрямом Other навичок не отримує
  напрям    track - за назвою посади й категорією на сторінці найму
  рівень    experience_level - за словами в назві посади («高级», «资深», «实习», Senior ...)
  формат    work_model - за словами remote / hybrid / on-site у назві чи описі
Латинські слова в правилах шукаються як цілі слова («intern» не збігається з «international»,
«sales» - із «Salesforce»); китайські - як частина рядка.
Чого немає (на відміну від розбору моделлю): перекладу назви посади. Навичка, якої немає у словнику, не потрапить у статистику -
словник доповнюється тут, з підвищенням KEYWORDS_VERSION.

Чисті функції, без мережі й бази.
"""

from __future__ import annotations

import re

from collectors._jobs_common import Skill

KEYWORDS_VERSION = "kw_v2"      # v2: англомовні вакансії (Adzuna): словник стеку даних, правила за цілими словами
METHOD = f"keywords:{KEYWORDS_VERSION}"

# (канонічна назва, категорія, латинські варіанти, китайські варіанти)
# Канонічні назви збігаються з уже наявними в dim_skills, щоб навички з різних джерел зливались.
SKILLS: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    # мови
    ("Python", "Language", ("Python",), ()),
    ("C++", "Language", ("C++", "CPP"), ()),
    ("Rust", "Language", ("Rust",), ()),
    ("Go", "Language", ("Go", "Golang"), ()),
    ("Java", "Language", ("Java",), ()),
    ("JavaScript", "Language", ("JavaScript",), ()),
    ("TypeScript", "Language", ("TypeScript",), ()),
    ("SQL", "Language", ("SQL",), ()),
    ("Scala", "Language", ("Scala",), ()),
    ("Shell", "Language", ("Shell", "Bash"), ()),
    ("Kotlin", "Language", ("Kotlin",), ()),
    ("C#", "Language", ("C#", ".NET"), ()),
    ("Swift", "Language", ("Swift",), ()),
    # фреймворки глибокого навчання
    ("PyTorch", "Deep Learning Framework", ("PyTorch", "Torch"), ()),
    ("TensorFlow", "Deep Learning Framework", ("TensorFlow",), ()),
    ("JAX", "Deep Learning Framework", ("JAX",), ()),
    ("Deep Learning", "Deep Learning Framework", ("Deep Learning",), ("深度学习",)),
    # апаратний рівень
    ("CUDA", "AI Hardware/Kernel", ("CUDA",), ()),
    ("GPU", "AI Hardware/Kernel", ("GPU",), ("显卡",)),
    ("RDMA", "AI Hardware/Kernel", ("RDMA",), ()),
    ("InfiniBand", "AI Hardware/Kernel", ("InfiniBand",), ()),
    ("NCCL", "AI Hardware/Kernel", ("NCCL",), ()),
    ("Triton", "AI Hardware/Kernel", ("Triton",), ()),
    ("LLVM", "AI Hardware/Kernel", ("LLVM",), ()),
    ("MLIR", "AI Hardware/Kernel", ("MLIR",), ()),
    ("MPI", "AI Hardware/Kernel", ("MPI", "OpenMPI"), ()),
    ("High-Performance Computing", "AI Hardware/Kernel", ("HPC",), ("高性能计算",)),
    # обслуговування моделей
    ("vLLM", "AI Serving", ("vLLM",), ()),
    ("SGLang", "AI Serving", ("SGLang",), ()),
    ("TensorRT", "AI Serving", ("TensorRT",), ()),
    ("ONNX", "AI Serving", ("ONNX",), ()),
    ("Megatron", "AI Serving", ("Megatron",), ()),
    ("Distributed Training", "AI Serving", ("Distributed Training",), ("分布式训练",)),
    ("Inference Optimization", "AI Serving", ("Inference Optimization",), ("推理优化", "推理加速", "推理引擎", "推理框架")),
    # лише «模型量化» тощо: саме «量化» в китайських вакансіях часто означає кількісну торгівлю
    ("Model Quantization", "AI Serving", ("Quantization",), ("模型量化", "量化压缩", "量化推理", "量化部署")),
    # навчання після попереднього
    ("Reinforcement Learning", "Post-training", ("Reinforcement Learning",), ("强化学习",)),
    ("RLHF", "Post-training", ("RLHF",), ()),
    ("PPO", "Post-training", ("PPO",), ()),
    ("GRPO", "Post-training", ("GRPO",), ()),
    ("DPO", "Post-training", ("DPO",), ()),
    ("Fine-tuning", "Post-training", ("Fine-tuning", "Finetuning", "Finetune", "Fine-tune", "LoRA"), ("微调",)),
    ("Pre-training", "Post-training", ("Pre-training", "Pretraining"), ("预训练",)),
    ("Model Distillation", "Post-training", ("Distillation",), ("蒸馏",)),
    ("Model Evaluation", "Post-training", ("Benchmark",), ("模型评测", "模型评估", "评测体系")),
    # прикладний ШІ
    ("LLM", "Applied AI", ("LLM", "LLMs", "Large Language Model", "Large Language Models"),
     ("大模型", "大语言模型", "语言模型")),
    ("AI Agents", "Applied AI", ("Agent", "Agents", "Agentic"), ("智能体",)),
    ("RAG", "Applied AI", ("RAG",), ("检索增强",)),
    ("Machine Learning", "Applied AI", ("Machine Learning",), ("机器学习",)),
    ("Natural Language Processing", "Applied AI", ("NLP",), ("自然语言处理",)),
    ("Computer Vision", "Applied AI", ("Computer Vision",), ("计算机视觉", "视觉算法")),
    ("Multimodal", "Applied AI", ("Multimodal", "Multi-modal"), ("多模态",)),
    ("Speech", "Applied AI", ("ASR", "TTS"), ("语音识别", "语音合成")),
    ("Transformer", "Applied AI", ("Transformer", "Transformers"), ()),
    ("Diffusion Models", "Applied AI", ("Diffusion",), ("扩散模型",)),
    ("Recommender Systems", "Applied AI", (), ("推荐系统", "推荐算法")),
    ("Prompt Engineering", "Applied AI", ("Prompt Engineering", "Prompt"), ("提示词",)),
    ("Model Context Protocol", "Applied AI", ("MCP",), ()),
    ("LangChain", "Applied AI", ("LangChain",), ()),
    ("Generative AI", "Applied AI", ("Generative AI", "GenAI", "Gen AI"), ("生成式",)),
    ("MLOps", "Applied AI", ("MLOps", "MLflow", "Kubeflow", "SageMaker", "Vertex AI"), ()),
    ("Hugging Face", "Applied AI", ("Hugging Face", "HuggingFace"), ()),
    ("LlamaIndex", "Applied AI", ("LlamaIndex",), ()),
    ("Vector DB", "Applied AI", ("Milvus", "Faiss", "Vector Database"), ("向量数据库", "向量检索")),
    ("AI Alignment", "Applied AI", ("Alignment", "AI Safety", "Red Teaming", "Red Team"), ("模型安全", "红队", "对齐研究")),
    ("Synthetic Data", "Applied AI", ("Synthetic Data",), ("合成数据", "数据合成")),
    # платформи даних і бази
    ("Spark", "Data Platform", ("Spark", "Apache Spark"), ()),
    ("PySpark", "Data Platform", ("PySpark",), ()),
    ("Databricks", "Data Platform", ("Databricks",), ()),
    ("Snowflake", "Data Platform", ("Snowflake",), ()),
    ("BigQuery", "Data Platform", ("BigQuery",), ()),
    ("Redshift", "Data Platform", ("Redshift",), ()),
    ("Azure Synapse", "Data Platform", ("Synapse",), ()),
    ("Microsoft Fabric", "Data Platform", ("Microsoft Fabric", "MS Fabric"), ()),
    ("dbt", "Data Platform", ("dbt",), ()),
    ("Apache Iceberg", "Data Platform", ("Iceberg",), ()),
    ("Delta Lake", "Data Platform", ("Delta Lake",), ()),
    ("Dagster", "Data Platform", ("Dagster",), ()),
    ("Prefect", "Data Platform", ("Prefect",), ()),
    ("Fivetran", "Data Platform", ("Fivetran",), ()),
    ("Informatica", "Data Platform", ("Informatica",), ()),
    ("SSIS", "Data Platform", ("SSIS",), ()),
    ("AWS Glue", "Data Platform", ("AWS Glue", "Glue"), ()),
    ("Azure Data Factory", "Data Platform", ("Azure Data Factory", "Data Factory", "ADF"), ()),
    ("Data Warehousing", "Data Platform", ("Data Warehouse", "Data Warehousing", "Data Warehouses"), ("数据仓库", "数仓")),
    ("Data Modeling", "Data Platform", ("Data Modeling", "Data Modelling"), ("数据建模",)),
    ("Data Pipelines", "Data Platform", ("Data Pipeline", "Data Pipelines"), ("数据管道", "数据流水线")),
    ("Data Lake", "Data Platform", ("Data Lake", "Lakehouse", "Data Lakehouse"), ("数据湖",)),
    ("Flink", "Data Platform", ("Flink",), ()),
    ("Hadoop", "Data Platform", ("Hadoop", "HDFS"), ()),
    ("Hive", "Data Platform", ("Hive",), ()),
    ("Apache Kafka", "Data Platform", ("Kafka",), ()),
    ("Airflow", "Data Platform", ("Airflow",), ()),
    ("ETL", "Data Platform", ("ETL", "ELT"), ()),
    ("Ray", "Data Platform", ("Ray",), ()),
    ("MySQL", "Database", ("MySQL",), ()),
    ("SQL Server", "Database", ("SQL Server", "MSSQL", "T-SQL"), ()),
    ("Oracle", "Database", ("Oracle",), ()),
    ("NoSQL", "Database", ("NoSQL",), ()),
    ("DynamoDB", "Database", ("DynamoDB",), ()),
    ("Cassandra", "Database", ("Cassandra",), ()),
    ("DuckDB", "Database", ("DuckDB",), ()),
    ("PostgreSQL", "Database", ("PostgreSQL", "Postgres"), ()),
    ("Redis", "Database", ("Redis",), ()),
    ("MongoDB", "Database", ("MongoDB",), ()),
    ("ClickHouse", "Database", ("ClickHouse",), ()),
    ("Elasticsearch", "Database", ("Elasticsearch",), ()),
    ("Ceph", "Database", ("Ceph",), ()),
    ("RocksDB", "Database", ("RocksDB",), ()),
    ("Distributed Storage", "Database", ("Distributed Storage",), ("分布式存储",)),
    # хмари та експлуатація
    ("AWS", "Cloud", ("AWS",), ()),
    ("Azure", "Cloud", ("Azure",), ()),
    ("GCP", "Cloud", ("GCP",), ()),
    ("Alibaba Cloud", "Cloud", ("Aliyun",), ("阿里云",)),
    ("Kubernetes", "DevOps", ("Kubernetes", "K8s"), ()),
    ("Docker", "DevOps", ("Docker",), ()),
    ("Linux", "DevOps", ("Linux",), ()),
    ("Terraform", "DevOps", ("Terraform",), ()),
    ("Slurm", "DevOps", ("Slurm",), ()),
    ("Distributed Systems", "DevOps", ("Distributed Systems",), ("分布式系统",)),
    # інструменти
    ("Git", "Tool", ("Git",), ()),
    ("CI/CD", "DevOps", ("CI/CD", "CICD", "Jenkins", "GitHub Actions", "GitLab CI"), ("持续集成",)),
    ("Power BI", "Tool", ("Power BI", "PowerBI"), ()),
    ("Tableau", "Tool", ("Tableau",), ()),
    ("Looker", "Tool", ("Looker",), ()),
    ("Pandas", "Tool", ("Pandas",), ()),
    ("NumPy", "Tool", ("NumPy",), ()),
    ("scikit-learn", "Tool", ("scikit-learn", "sklearn"), ()),
    ("SAS", "Tool", ("SAS",), ()),
    ("FastAPI", "Tool", ("FastAPI",), ()),
    ("Django", "Tool", ("Django",), ()),
    ("Flask", "Tool", ("Flask",), ()),
    ("REST API", "Tool", ("REST API", "REST APIs", "RESTful"), ()),
    ("GraphQL", "Tool", ("GraphQL",), ()),
    ("gRPC", "Tool", ("gRPC",), ()),
    ("React", "Tool", ("React",), ()),
    ("Vue", "Tool", ("Vue",), ()),
    ("Node.js", "Tool", ("Node.js", "NodeJS"), ()),
    ("Prometheus", "Tool", ("Prometheus",), ()),
    ("Grafana", "Tool", ("Grafana",), ()),
    ("A/B Testing", "Tool", ("A/B Testing", "AB Test"), ("AB实验", "A/B实验")),
]

# Короткі або схожі на звичайні слова назви шукаються з урахуванням регістру («Go», а не «go»).
CASE_SENSITIVE = {"Go", "Ray", "Git", "Swift", "Rust", "Shell", "Bash", "Spark", "Hive", "Vue", "React",
                  "Glue", "Oracle", "Looker", "Prefect", "Flask", "Synapse", "Iceberg", "Snowflake", "dbt",
                  "Agent", "Agents", "Prompt", "Triton", "Torch", "Scala", "Java", "Alignment", "Benchmark",
                  "Diffusion", "Distillation", "Quantization", "Transformer", "Transformers"}

_EDGE = r"A-Za-z0-9_"


def _latin_re(term: str) -> re.Pattern:
    if term == "Go":      # мова Go, а не «Go-to-market» чи «Go to ...»
        return re.compile(rf"(?<![{_EDGE}.\-])Go(?![{_EDGE}+#\-])(?! to\b)")
    """Ціле слово: поруч не може бути латинської літери чи цифри (китайський ієрогліф - може).
    «Java» не збігається з «JavaScript», «C++» шукається як є."""
    flags = 0 if (term in CASE_SENSITIVE or (len(term) <= 4 and term.isupper())) else re.I
    tail = rf"(?![{_EDGE}+#])" if not term.endswith(("+", "#")) else rf"(?![{_EDGE}])"
    head = rf"(?<![{_EDGE}.\-])" if not term.startswith(".") else rf"(?<![{_EDGE}])"
    return re.compile(rf"{head}{re.escape(term)}{tail}", flags)


_COMPILED = [(name, cat, [_latin_re(t) for t in latin], zh) for name, cat, latin, zh in SKILLS]


def extract_skills(text: str) -> list[Skill]:
    """Навички зі словника, що згадані в тексті; кожна один раз, у порядку словника."""
    found = []
    for name, cat, patterns, zh in _COMPILED:
        if any(p.search(text) for p in patterns) or any(z in text for z in zh):
            found.append(Skill(name=name, category=cat))
    return found


# Слово правила: латинське - ціле слово, китайське - частина рядка.
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _word_re(words: tuple[str, ...]) -> re.Pattern:
    parts = [re.escape(w) if _CJK.search(w) else rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" for w in words]
    return re.compile("|".join(parts))


# Нетехнічні посади: напрям Other і без навичок. Опис такої вакансії (юрист, продажі, маркетинг)
# згадує «大模型» чи «Agent» як продукт компанії, а не як вимогу до фахівця - у попит на навички
# це не рахується. Перевіряється лише назва посади і раніше за TRACK_RULES.
# Якщо в назві є технічна роль (TECH_ROLE), посада технічна попри слово зі списку:
# «Data Engineer - Finance» чи «Sales Engineer» - інженери.
NON_TECH = _word_re((
    "产品经理", "产品运营", "运营", "销售", "市场", "营销", "法务", "律师", "财务", "税务", "会计", "审计",
    "内控", "招聘", "人力", "采购", "投资", "公关", "品牌", "商务", "行政", "设计师", "客户成功", "客服",
    "项目管理", "合规", "政府", "战略", "pr内容",
    "hrbp", "hr", "talent partner", "talent acquisition", "recruiter", "recruiting", "recruitment", "pmo",
    "business development", "marketing", "sales", "legal", "finance", "investor", "branding", "pr", "gtm",
    "seo", "accountant", "account manager", "account executive", "customer success", "product manager",
    "project manager", "program manager", "procurement", "paralegal", "copywriter"))
TECH_ROLE = _word_re((
    "engineer", "engineers", "engineering", "developer", "scientist", "architect", "programmer", "sre",
    "devops", "analyst", "工程师", "研发", "算法", "开发", "架构师", "程序", "研究员"))

# Напрям: перший рядок, слова якого є в назві посади або категорії. Порядок має значення:
# інженерія даних і аналітика - раніше за машинне навчання («AI Data Engineer» - інженер даних).
TRACK_RULES: list[tuple[str, re.Pattern]] = [(t, _word_re(w)) for t, w in [
    ("AI Alignment", ("alignment", "ai safety", "safety researcher", "red team", "red teaming",
                      "对齐", "模型安全", "红队", "安全研究", "ai 安全", "ai安全")),
    ("Data Engineering", ("data engineer", "data engineers", "data engineering", "data platform", "big data",
                          "etl", "elt", "data pipeline", "data pipelines", "data warehouse", "databricks",
                          "snowflake", "dataops", "data architect", "data infrastructure",
                          "数据工程", "数据平台", "数据开发", "数仓", "数据仓库", "大数据", "存储", "数据采集", "爬虫",
                          "数据标注")),
    ("Analytics Engineering", ("analytics engineer", "analytics", "analyst", "business intelligence", "bi",
                               "power bi", "tableau", "reporting", "数据分析", "分析师", "商业分析")),
    ("Machine Learning", ("machine learning", "ml", "mlops", "ai", "artificial intelligence", "deep learning",
                          "genai", "generative", "llm", "llms", "nlp", "aigc", "data scientist", "data science",
                          "research", "researcher", "applied scientist", "computer vision", "agent", "agents",
                          "prompt",
                          "算法", "模型", "深度学习", "机器学习", "研究员", "研究科学家", "训练", "推理", "多模态",
                          "强化学习", "智能体", "语音", "视觉", "评测", "提示词", "数据科学")),
    ("Backend", ("backend", "back-end", "back end", "software engineer", "software developer", "full stack",
                 "fullstack", "full-stack", "developer", "engineer", "engineering", "infra", "infrastructure",
                 "sre", "devops", "platform", "cloud", "architect", "programmer", "gpu",
                 "后端", "服务端", "后台", "架构", "基础架构", "运维", "分布式", "系统", "平台", "全栈", "前端",
                 "客户端", "开发工程师", "软件工程师", "测试", "网络", "编译", "集群", "高性能", "安全工程", "研发",
                 "工程师", "开发", "程序", "技术类", "逆向", "安全")),
]]

LEVEL_RULES: list[tuple[str, re.Pattern]] = [(lv, _word_re(w)) for lv, w in [
    ("Junior", ("junior", "jr", "intern", "internship", "graduate", "new grad", "entry level", "entry-level",
                "trainee", "apprentice", "实习", "校招", "应届", "管培", "初级")),
    ("Lead/Staff", ("lead", "leader", "staff", "principal", "head", "director", "vp", "chief",
                    "负责人", "总监", "首席", "主管", "架构师")),
    ("Senior", ("senior", "sr", "expert", "高级", "资深", "专家")),
    ("Mid", ("mid", "mid-level", "mid level", "intermediate", "中级")),
]]

_REMOTE = _word_re(("remote", "work from home", "wfh", "fully remote", "远程"))
_HYBRID = _word_re(("hybrid", "混合办公"))
_ONSITE = _word_re(("on-site", "onsite", "on site", "in-office", "in office", "驻场"))


def is_non_tech(title: str) -> bool:
    t = title.lower()
    return bool(NON_TECH.search(t)) and not TECH_ROLE.search(t)


def classify_track(title: str, category: str | None = None) -> str:
    if is_non_tech(title):
        return "Other"
    text = f"{title} {category or ''}".lower()
    for track, pattern in TRACK_RULES:
        if pattern.search(text):
            return track
    return "Other"


def classify_level(title: str) -> str:
    """Рівень лише з назви посади: в описі слова «高级» чи «实习» трапляються з іншого приводу."""
    text = title.lower()
    for level, pattern in LEVEL_RULES:
        if pattern.search(text):
            return level
    return "Not Specified"


def classify_work_model(title: str, description: str) -> str:
    """Формат роботи за прямою згадкою; «hybrid» важить більше за «remote» («hybrid/remote»)."""
    text = f"{title} {description or ''}".lower()
    if _HYBRID.search(text):
        return "Hybrid"
    if _REMOTE.search(text):
        return "Remote"
    if _ONSITE.search(text):
        return "On-site"
    return "Not Specified"


def extract(title: str, description: str, category: str | None = None) -> dict:
    """Поля факту вакансії, які раніше давала модель. Назва лишається мовою оригіналу."""
    description = description or ""
    track = classify_track(title, category)
    return {
        "experience_level": classify_level(title),
        "work_model": classify_work_model(title, description),
        "track": track,
        "extraction_method": METHOD,
        "prompt_version": KEYWORDS_VERSION,
        # посада без технічного напряму (Other) навичок не отримує - див. NON_TECH
        "_skills": extract_skills(f"{title}\n{category or ''}\n{description or ''}") if track != "Other" else [],
    }
