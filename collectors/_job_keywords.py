"""
collectors/_job_keywords.py
Розбір вакансії ключовими словами, без мовної моделі.

Навіщо: вакансії китайських лабораторій (кілька сотень оголошень) розбираються однаково,
відтворювано і без витрат квоти Gemini. Що слово означає - записано тут, у словнику; та сама
вакансія завжди дає той самий результат.

Що визначається:
  навички   назви технологій і методів зі словника SKILLS (латинські назви + китайські відповідники);
            лише для технічних посад: вакансія з напрямом Other навичок не отримує
  напрям    track - за назвою посади й категорією на сторінці найму
  рівень    experience_level - за словами в назві посади («高级», «资深», «实习», Senior ...)
Чого немає (на відміну від розбору моделлю): перекладу назви посади і формату роботи
(work_model завжди "Not Specified"). Навичка, якої немає у словнику, не потрапить у статистику -
словник доповнюється тут, з підвищенням KEYWORDS_VERSION.

Чисті функції, без мережі й бази.
"""

from __future__ import annotations

import re

from collectors._jobs_common import Skill

KEYWORDS_VERSION = "kw_v1"
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
    ("LlamaIndex", "Applied AI", ("LlamaIndex",), ()),
    ("Vector DB", "Applied AI", ("Milvus", "Faiss", "Vector Database"), ("向量数据库", "向量检索")),
    ("AI Alignment", "Applied AI", ("Alignment", "AI Safety", "Red Teaming", "Red Team"), ("模型安全", "红队", "对齐研究")),
    ("Synthetic Data", "Applied AI", ("Synthetic Data",), ("合成数据", "数据合成")),
    # платформи даних і бази
    ("Spark", "Data Platform", ("Spark", "PySpark"), ()),
    ("Flink", "Data Platform", ("Flink",), ()),
    ("Hadoop", "Data Platform", ("Hadoop", "HDFS"), ()),
    ("Hive", "Data Platform", ("Hive",), ()),
    ("Apache Kafka", "Data Platform", ("Kafka",), ()),
    ("Airflow", "Data Platform", ("Airflow",), ()),
    ("ETL", "Data Platform", ("ETL",), ("数据仓库", "数仓")),
    ("Ray", "Data Platform", ("Ray",), ()),
    ("MySQL", "Database", ("MySQL",), ()),
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
                  "Agent", "Agents", "Prompt", "Triton", "Torch", "Scala", "Java", "Alignment", "Benchmark",
                  "Diffusion", "Distillation", "Quantization", "Transformer", "Transformers"}

_EDGE = r"A-Za-z0-9_"


def _latin_re(term: str) -> re.Pattern:
    if term == "Go":      # мова Go, а не «Go-to-market» чи «Go to ...»
        return re.compile(rf"(?<![{_EDGE}.\-])Go(?![{_EDGE}+#\-])(?! to\b)")
    """Ціле слово: поруч не може бути латинської літери чи цифри (китайський ієрогліф - може).
    «Java» не збігається з «JavaScript», «C++» шукається як є."""
    flags = 0 if (term in CASE_SENSITIVE or (len(term) <= 4 and term.isupper())) else re.I
    tail = rf"(?![{_EDGE}+#])" if not term.endswith("+") else rf"(?![{_EDGE}])"
    return re.compile(rf"(?<![{_EDGE}.\-]){re.escape(term)}{tail}", flags)


_COMPILED = [(name, cat, [_latin_re(t) for t in latin], zh) for name, cat, latin, zh in SKILLS]


def extract_skills(text: str) -> list[Skill]:
    """Навички зі словника, що згадані в тексті; кожна один раз, у порядку словника."""
    found = []
    for name, cat, patterns, zh in _COMPILED:
        if any(p.search(text) for p in patterns) or any(z in text for z in zh):
            found.append(Skill(name=name, category=cat))
    return found


# Нетехнічні посади: напрям Other і без навичок. Опис такої вакансії (юрист, продажі, маркетинг)
# згадує «大模型» чи «Agent» як продукт компанії, а не як вимогу до фахівця - у попит на навички
# це не рахується. Перевіряється лише назва посади і раніше за TRACK_RULES.
NON_TECH = ("产品经理", "产品运营", "运营", "销售", "市场", "营销", "法务", "律师", "财务", "税务", "会计", "审计",
            "内控", "招聘", "人力", "hrbp", "talent", "采购", "投资", "公关", "品牌", "商务", "行政", "设计师",
            "客户成功", "客服", "pmo", "项目管理", "business development", "marketing", "sales", "recruit",
            "legal", "finance", "investor", "branding", " pr", "pr内容", "gtm", "seo", "合规", "政府", "战略")

# Напрям: перший рядок, слова якого є в назві посади або категорії. Порядок має значення.
TRACK_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("AI Alignment", ("alignment", "safety", "red team", "对齐", "模型安全", "红队", "安全研究", "ai 安全", "ai安全")),
    ("Machine Learning", ("算法", "模型", "深度学习", "机器学习", "研究员", "研究科学家", "训练", "推理", "多模态",
                          "llm", "machine learning", "research", "nlp", "aigc", "强化学习", "智能体", "agent",
                          "语音", "视觉", "评测", "prompt", "提示词")),
    ("Data Engineering", ("数据工程", "数据平台", "数据开发", "数仓", "数据仓库", "大数据", "存储", "etl",
                          "data engineer", "data platform", "数据采集", "爬虫", "数据标注")),
    ("Analytics Engineering", ("数据分析", "分析师", "data analyst", "商业分析", "数据科学", "data scien")),
    ("Backend", ("后端", "服务端", "backend", "后台", "架构", "基础架构", "infra", "sre", "运维", "分布式", "系统",
                 "平台", "全栈", "前端", "客户端", "开发工程师", "软件工程师", "engineer", "测试", "网络", "编译",
                 "gpu", "集群", "高性能", "安全工程", "研发", "工程师", "开发", "developer", "程序", "技术类",
                 "逆向", "安全")),
]

LEVEL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Junior", ("实习", "intern", "校招", "应届", "管培", "初级", "junior", "new grad")),
    ("Lead/Staff", ("负责人", "总监", "leader", "lead", "staff", "principal", "首席", "主管", "架构师", "head of")),
    ("Senior", ("高级", "资深", "专家", "senior", "sr.")),
]


def is_non_tech(title: str) -> bool:
    t = f" {title.lower()}"
    return any(w in t for w in NON_TECH)


def classify_track(title: str, category: str | None = None) -> str:
    if is_non_tech(title):
        return "Other"
    text = f"{title} {category or ''}".lower()
    for track, words in TRACK_RULES:
        if any(w in text for w in words):
            return track
    return "Other"


def classify_level(title: str) -> str:
    """Рівень лише з назви посади: в описі слова «高级» чи «实习» трапляються з іншого приводу."""
    text = title.lower()
    for level, words in LEVEL_RULES:
        if any(w in text for w in words):
            return level
    return "Not Specified"


def extract(title: str, description: str, category: str | None = None) -> dict:
    """Поля факту вакансії, які раніше давала модель. Назва лишається мовою оригіналу."""
    track = classify_track(title, category)
    return {
        "experience_level": classify_level(title),
        "work_model": "Not Specified",
        "track": track,
        "extraction_method": METHOD,
        "prompt_version": KEYWORDS_VERSION,
        # посада без технічного напряму (Other) навичок не отримує - див. NON_TECH
        "_skills": extract_skills(f"{title}\n{category or ''}\n{description or ''}") if track != "Other" else [],
    }
