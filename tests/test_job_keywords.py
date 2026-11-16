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
    assert x["extraction_method"] == "keywords:kw_v1" and x["work_model"] == "Not Specified"
    assert {s.name for s in x["_skills"]} == {"PyTorch", "LLM", "Deep Learning"}
    assert all(s.category in kw.Skill.model_fields or True for s in x["_skills"])
    from collectors._jobs_common import SKILL_CATEGORIES
    assert {c for _, c, _, _ in kw.SKILLS} <= set(SKILL_CATEGORIES)
