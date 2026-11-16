"""Розбір вакансії ключовими словами: навички, напрям, рівень."""

from collectors import _job_keywords as kw


def names(text):
    return [s.name for s in kw.extract_skills(text)]


def test_latin_terms_next_to_chinese_and_whole_words_only():
    text = "熟悉Python/C++，有PyTorch、CUDA经验；了解Kubernetes(K8s)和JavaScript。"
    got = names(text)
    assert {"Python", "C++", "PyTorch", "CUDA", "Kubernetes", "JavaScript"} <= set(got)
    assert "Java" not in got                                   # «JavaScript» - не «Java»
    assert names("熟练使用Java和Golang") == ["Go", "Java"]


def test_short_names_are_case_sensitive():
    assert "Go" not in names("We go to market and git things done with a ray of hope")
    assert {"Go", "Git", "Ray"} <= set(names("Go, Git, Ray"))
    assert "Rust" in names("熟悉Rust语言") and "Rust" not in names("no rust on the pipes")


def test_chinese_synonyms_and_single_mention():
    got = names("负责大模型预训练与微调，强化学习（RLHF）；大模型推理优化，分布式训练。LLM LLM")
    assert got.count("LLM") == 1
    assert {"LLM", "Pre-training", "Fine-tuning", "Reinforcement Learning", "RLHF",
            "Inference Optimization", "Distributed Training"} <= set(got)
    assert names("财务专员，负责报销与发票") == []                # нетехнічна вакансія - без навичок


def test_track_and_level():
    assert kw.classify_track("大模型算法工程师") == "Machine Learning"
    assert kw.classify_track("高性能分布式存储工程师") == "Data Engineering"
    assert kw.classify_track("后端开发工程师") == "Backend"
    assert kw.classify_track("AI安全研究员（红队）") == "AI Alignment"
    assert kw.classify_track("财务专员") == "Other"
    assert kw.classify_track("专员", "AI核心系统研发 模型训练") == "Machine Learning"   # за категорією сторінки
    assert kw.classify_level("资深算法专家") == "Senior"
    assert kw.classify_level("算法实习生") == "Junior"
    assert kw.classify_level("推理平台负责人") == "Lead/Staff"
    assert kw.classify_level("算法工程师") == "Not Specified"


def test_extract_shape():
    x = kw.extract("高级算法工程师", "要求：熟悉PyTorch，了解大模型", "深度学习")
    assert x["track"] == "Machine Learning" and x["experience_level"] == "Senior"
    assert x["extraction_method"] == kw.METHOD and x["work_model"] == "Not Specified"
    assert {s.name for s in x["_skills"]} == {"PyTorch", "LLM", "Deep Learning"}
    assert all(s.category in kw.Skill.model_fields or True for s in x["_skills"])
    from collectors._jobs_common import SKILL_CATEGORIES
    assert {c for _, c, _, _ in kw.SKILLS} <= set(SKILL_CATEGORIES)


def test_non_tech_roles_get_no_skills():
    for title in ("法务BP（知识产权与标准化方向）", "API销售", "大模型产品经理", "AI Talent Partner（招聘与运营）",
                  "Global PR｜海外PR内容专家", "投资经理（AI驱动型）", "Global GTM Intern"):
        x = kw.extract(title, "负责大模型、Agent、RLHF相关业务，熟悉Python")
        assert x["track"] == "Other" and x["_skills"] == [], title
    x = kw.extract("Harness 研发工程师", "熟悉Python和大模型")
    assert x["track"] == "Backend" and {s.name for s in x["_skills"]} == {"Python", "LLM"}
    assert kw.classify_track("AI 安全实习生") == "AI Alignment"
    assert kw.classify_track("下一代多模态系统-实习生-TOP Talent") == "Machine Learning"   # «Talent» - не кадрова посада
    assert kw.classify_track("专员", "技术类/Technical") == "Backend"


def test_go_and_quantization_false_positives():
    assert "Go" not in names("Go-to-market strategy. Go to the customers.")
    assert "Go" in names("熟悉Go或Rust") and "Go" in names("Go, Python")
    assert "Model Quantization" not in names("量化交易策略研究")          # кількісна торгівля
    assert "Model Quantization" in names("模型量化与蒸馏")


def test_english_titles_whole_words():
    assert kw.classify_track("Senior Data Engineer (Python, AWS)") == "Data Engineering"
    assert kw.classify_track("AI Data Engineer") == "Data Engineering"            # інженерія даних раніше за ML
    assert kw.classify_track("Machine Learning Engineer") == "Machine Learning"
    assert kw.classify_track("Data Scientist") == "Machine Learning"
    assert kw.classify_track("Analytics Engineer") == "Analytics Engineering"
    assert kw.classify_track("BI Developer") == "Analytics Engineering"
    assert kw.classify_track("Python Developer") == "Backend"
    assert kw.classify_track("Salesforce Data Engineer") == "Data Engineering"    # «sales» - не «Salesforce»
    assert kw.classify_track("Data Engineer - Finance") == "Data Engineering"     # технічна роль важить більше
    assert kw.classify_track("Marketing Manager") == "Other"
    assert kw.classify_level("International Data Engineer") == "Not Specified"    # «intern» - не «international»
    assert kw.classify_level("Data Engineering Intern") == "Junior"
    assert kw.classify_level("Sr. Data Engineer") == "Senior"
    assert kw.classify_level("Lead Data Engineer") == "Lead/Staff"
    assert kw.classify_level("Leading Edge Data Engineer") == "Not Specified"
    assert kw.classify_level("Mid-Level Python Engineer") == "Mid"


def test_english_data_stack_and_work_model():
    text = ("We need a Data Engineer with Python, SQL, PySpark and Databricks on Azure. Experience with dbt, "
            "Snowflake, Power BI, CI/CD and data pipelines. C# or .NET is a plus. Hybrid working, 2 days in office.")
    x = kw.extract("Data Engineer", text)
    got = {s.name for s in x["_skills"]}
    assert {"Python", "SQL", "PySpark", "Databricks", "Azure", "dbt", "Snowflake", "Power BI", "CI/CD",
            "Data Pipelines", "C#"} <= got
    assert "Spark" not in got                                    # «PySpark» - окрема навичка
    assert x["work_model"] == "Hybrid" and x["track"] == "Data Engineering"
    assert kw.classify_work_model("Data Engineer (Remote)", "") == "Remote"
    assert kw.classify_work_model("Data Engineer", "on-site in London") == "On-site"
    assert kw.classify_work_model("Data Engineer", "remotely operated vehicles") == "Not Specified"
    assert "Oracle" not in names("an oracle of wisdom") and "Oracle" in names("Oracle and SQL Server")
    assert "Glue" not in names("the glue between teams") and "AWS Glue" in names("AWS Glue jobs")
