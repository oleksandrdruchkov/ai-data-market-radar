"""
collectors/arxiv_counts.py
Скільки статей ШІ щомісяця виходить на ArXiv за кожним напрямом -> fct_metric_values.
Без моделі: arXiv API повертає загальну кількість знайдених статей (opensearch:totalResults),
самі статті не завантажуються.

  arxiv_papers_total     усі статті місяця в категоріях ШІ (CATEGORIES), шт.
  arxiv_share_<напрям>   % статей місяця, що відповідають запиту напряму;
                         numerator = статей напряму, denominator = усіх статей
  arxiv_group_<група>    % статей місяця, що відповідають БУДЬ-ЯКОМУ напряму групи - один запит,
                         без повторного рахунку статей, які стосуються кількох напрямів

Дві групи (GROUPS) - два стовпчики графіка; назви з Регламенту ЄС про ШІ (2024/1689):
  autonomy  «Зростання автономності ШІ»  - ознаки з визначення системи ШІ, ст. 3(1);
  oversight «Людський нагляд і надійність ШІ» - ст. 14 «Людський нагляд», ст. 15 «Точність,
            надійність і кібербезпека». Ст. 14-15 формально стосуються систем високого ризику;
            тут їхні терміни - назви напрямів досліджень.

Напрями (DIRECTIONS) - пошук за фразами в назві та анотації. Фраза - рядок або пара списків
(A, B): стаття має містити щось з A І щось з B (напр., робот + модель ШІ). Одна стаття може
потрапити в кілька напрямів, тож частки напрямів групи в сумі більші за частку групи.

До фраз з коду додаються фрази, які людина схвалила на сторінці перевірки
(ops_phrase_candidates, status = 'added'; кандидатів готує metrics/arxiv_phrase_candidates.py).
Версія методу = METHOD_VERSION + відбиток повного списку фраз. Список змінився -> версія
змінилась -> збирач перераховує всю історію новим списком, щоб ряд не мав «шва».

Перший запуск - уся історія з ARXIV_COUNTS_START (за замовчуванням 2023-01), далі -
перерахунок двох останніх місяців (arXiv дописує статті із запізненням). Поточний місяць
неповний: is_estimate = true.

arXiv обмежує частоту (429), тому пауза 6 с і не більше ARXIV_COUNTS_MAX_QUERIES запитів
за запуск (130 = 10 місяців по 13 запитів). Місяць пишеться лише цілим (усі статті + усі напрями), а
наступний запуск продовжує з останнього записаного місяця, тож історія з 2023 року
збирається за 5 щоденних запусків.

Довгі запити (групи) йдуть методом POST: в адресу GET вони не вміщаються.

Змінні: ARXIV_COUNTS_START="2023-01-01"   ARXIV_COUNTS_MAX_QUERIES=130
        PHRASE_CHECK_DIRECTION=agents  (для --check: лише один напрям, щоб не впертися в ліміт)
        PHRASE_CHECK_PHRASES="a;b;c"   (для --check: довільні фрази-кандидати замість напрямів)
Запуск: python -m collectors.arxiv_counts
Перевірка фраз (лише друк, без запису): python -m collectors.arxiv_counts --check
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import calendar
import xml.etree.ElementTree as ET
from datetime import date

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult

API_URL = "https://export.arxiv.org/api/query"
HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}totalResults"
PAUSE_SECONDS = 6.0             # arXiv просить >= 3 с; на 3 с після ~80 запитів відповідав 429
RETRY_PAUSES = (60, 180, 300)   # 429/5xx: arXiv відпускає обмеження лише через кілька хвилин
MAX_QUERIES = 130               # запитів за один запуск; решта історії - наступного дня
METHOD_VERSION = "v2"           # v2: групи, нагляд у п'яти напрямах, роботи = робот + модель ШІ
POST_ABOVE = 1800               # довший запит - методом POST
TOTAL_ID = "arxiv_papers_total"

CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.RO", "cs.MA"]

Phrase = str | tuple  # рядок або (список A, список B): щось з A І щось з B

GROUPS: dict[str, tuple[str, str]] = {
    "autonomy": ("Зростання автономності ШІ", "Growth of AI autonomy"),
    "oversight": ("Людський нагляд і надійність ШІ", "Human oversight and robustness of AI"),
}

# id -> (назва UA, назва EN, фрази, група)
# arXiv зводить слова до основи: однина й множина, дефіс і пробіл дають однакові числа,
# тож у списку лише одна форма. Слова, чия основа збігається з поширеним словом, не беруться:
# «agentic» шукається як «agent», «scheming» - як «scheme», «interpretability» - як «interpret».
# Перевірити, скільки статей дає кожна фраза: python -m collectors.arxiv_counts --check
AI_MODEL = ["language model", "foundation model", "vision-language model", "LLM", "VLM", "large model"]
DIRECTIONS: dict[str, tuple[str, str, list[Phrase], str]] = {
    # ---------- зростання автономності ШІ (ст. 3(1)) ----------
    "agents": ("Автономне виконання завдань", "Autonomous task execution", [
        "LLM agent", "LLM-based agent", "language agent", "AI agent", "autonomous agent",
        "tool use", "tool calling", "function calling",
        "computer use", "GUI agent", "web agent", "coding agent", "software engineering agent",
        "agent memory", "long-horizon agent", "multi-agent LLM", "LLM-based multi-agent", "agent swarm",
    ], "autonomy"),
    # «self-improving» через основу ловить і «self-improvement»: будь-які методи, де модель
    # покращує власні відповіді чи навчання.
    "self_improvement": ("Адаптивність після розгортання", "Adaptiveness after deployment", [
        "self-improving", "recursive self-improvement", "self-evolving", "self-modifying",
    ], "autonomy"),
    # Лише роботи з моделлю ШІ: категорія cs.RO у вибірці, і слово «robot» саме по собі
    # рахувало б розмір категорії робототехніки та сезонність її конференцій.
    "robots": ("Вплив на фізичне середовище", "Influence on physical environments", [
        "vision-language-action", "VLA model", "embodied AI", "embodied agent",
        "robot foundation model", "generalist robot policy",
        (["robot", "humanoid", "embodied"], AI_MODEL),
    ], "autonomy"),
    "reasoning": ("Здатність до висновків", "Inference capability", [
        "test-time compute", "test-time scaling", "inference-time compute", "inference-time scaling",
        "chain of thought", "long chain-of-thought", "reasoning model", "large reasoning model",
        "reinforcement learning with verifiable rewards", "verifiable rewards",
        "process reward model", "latent reasoning", "thinking tokens",
    ], "autonomy"),
    "ai_science": ("Автономні наукові дослідження", "Autonomous scientific research", [
        "AI scientist", "AI co-scientist",
        "automated scientific discovery", "autonomous scientific discovery",
        "autonomous research", "automated research", "research agent",
        "automated AI research", "AI research automation",
        "automated machine learning research", "automated alignment research",
        "automated hypothesis generation", "LLM-driven discovery",
        "self-driving laboratory", "autonomous laboratory",
    ], "autonomy"),
    # ---------- людський нагляд і надійність ШІ (ст. 14, 15) ----------
    "oversight": ("Людський нагляд", "Human oversight", [
        "human oversight", "scalable oversight", "AI control", "chain-of-thought monitoring",
        "corrigibility",
    ], "oversight"),
    "understanding": ("Розуміння можливостей і обмежень ШІ", "Understanding AI capacities and limitations", [
        "mechanistic interpretability", "sparse autoencoder", "dangerous capabilities",
    ], "oversight"),
    "robustness": ("Стійкість і кібербезпека", "Robustness and cybersecurity", [
        "red teaming", "jailbreak", "prompt injection",
    ], "oversight"),
    "undesired": ("Виявлення небажаної поведінки", "Detecting undesirable behaviour", [
        "deceptive alignment", "emergent misalignment", "alignment faking", "in-context scheming",
        "sandbagging", "reward hacking", "evaluation awareness", "model organisms",
    ], "oversight"),
    "risk": ("Запобігання ризикам для безпеки та прав людини", "Preventing risks to safety and rights", [
        "AI safety", "AI alignment", "value alignment", "alignment of language models",
    ], "oversight"),
}


def label(p: Phrase) -> str:
    """Підпис фрази для журналу: рядок або «A1|A2 + B1|B2»."""
    return p if isinstance(p, str) else " + ".join("|".join(g) for g in p)


def plain_terms(phrases: list[Phrase]) -> list[str]:
    """Рядки для звірки з навичками (кандидати фраз): для пари - перший список (що саме)."""
    out: list[str] = []
    for p in phrases:
        out += [p] if isinstance(p, str) else list(p[0])
    return out


def term(p: Phrase) -> str:
    if isinstance(p, str):
        return f'ti:"{p}" OR abs:"{p}"'
    return "(" + " AND ".join("(" + " OR ".join(f'ti:"{x}" OR abs:"{x}"' for x in g) + ")" for g in p) + ")"


def group_phrases(directions: dict, group: str) -> list[Phrase]:
    return [p for (_, _, ph, g) in directions.values() if g == group for p in ph]


# Контрольні пари для --check: якщо числа в парі майже однакові, arXiv зводить їх до однієї основи.
STEM_CHECKS = [("agentic", "agent"), ("scheming", "scheme"), ("interpretability", "interpret")]


def merge_phrases(base: dict, extra: list[dict]) -> dict:
    """Фрази з коду + схвалені людиною (рядки ops_phrase_candidates: phrase, direction).
    Дублікати (без різниці регістру) і невідомі напрями відкидаються."""
    out = {k: (ua, en, list(ph), g) for k, (ua, en, ph, g) in base.items()}
    for r in extra:
        k, phrase = r.get("direction"), (r.get("phrase") or "").strip()
        if k not in out or not phrase:
            continue
        if phrase.lower() not in {label(p).lower() for p in out[k][2]}:
            out[k][2].append(phrase)
    return out


def fingerprint(directions: dict) -> str:
    """Короткий відбиток списку фраз і категорій: інший список - інший відбиток."""
    flat = json.dumps([CATEGORIES] + [[k, g, sorted(label(p).lower() for p in ph)]
                                      for k, (_, _, ph, g) in sorted(directions.items())], ensure_ascii=False)
    return hashlib.sha1(flat.encode("utf-8")).hexdigest()[:8]


def group_id(group: str) -> str:
    return f"arxiv_group_{group}"


def share_id(direction: str) -> str:
    return f"arxiv_share_{direction}"


def month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])


def months_between(start: date, end: date) -> list[date]:
    """Перші дні місяців від start до end включно."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_query(month: date, phrases: list[Phrase] | None) -> str:
    """Запит arXiv: категорії ШІ, (фрази в назві чи анотації), дата подання в межах місяця."""
    first, last = month_bounds(month)
    cats = " OR ".join(f"cat:{c}" for c in CATEGORIES)
    when = f"submittedDate:[{first:%Y%m%d}0000 TO {last:%Y%m%d}2359]"
    parts = [f"({cats})"]
    if phrases:
        parts.append("(" + " OR ".join(term(p) for p in phrases) + ")")
    parts.append(when)
    return " AND ".join(parts)


def parse_total(xml_text: str) -> int:
    """Чиста функція: opensearch:totalResults з відповіді arXiv. Немає - помилка, а не нуль."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"arXiv: відповідь не XML: {xml_text[:120]!r}") from e
    node = root.find(OPENSEARCH)
    if node is None or not (node.text or "").strip().isdigit():
        raise ValueError(f"arXiv: немає totalResults: {xml_text[:200]!r}")
    return int(node.text.strip())


class ArxivCounts(MetricSeriesCollector):
    source = "arxiv_counts"
    collector_version = "1"
    method_version = METHOD_VERSION

    def __init__(self, *a, sleep=time.sleep, today: date | None = None, **k):
        super().__init__(*a, **k)
        self.sleep = sleep
        self.today = today or date.today()
        self._calls = 0
        self.directions = merge_phrases(DIRECTIONS, self.approved_phrases())
        self.method_version = f"{METHOD_VERSION}-{fingerprint(self.directions)}"

    def approved_phrases(self) -> list[dict]:
        try:
            return self.db.select("ops_phrase_candidates", "phrase,direction", eq={"status": "added"})
        except Exception as e:                      # таблиці ще немає - працюємо зі списком з коду
            self.log.warning(f"ops_phrase_candidates недоступна: {e}")
            return []

    def since(self, metric_id: str, region: str) -> date:
        """Перший запуск або змінений список фраз - уся історія з ARXIV_COUNTS_START;
        інакше - два останні місяці або місяць, на якому перервався минулий збір."""
        rows = self.db.select("fct_metric_values", "period_start,method_version",
                              eq={"metric_id": metric_id, "region": region},
                              order="period_start", desc=True, limit=1)
        if not rows or rows[0].get("method_version") != self.method_version:
            return date.fromisoformat(os.getenv("ARXIV_COUNTS_START", "2023-01-01")).replace(day=1)
        y, m = self.today.year, self.today.month - 1
        if m == 0:
            y, m = y - 1, 12
        last_saved = date.fromisoformat(str(rows[0]["period_start"])[:10])
        return min(last_saved, date(y, m, 1))       # збір історії перервався - продовжити звідти

    def count(self, query: str) -> int:
        if self._calls:
            self.sleep(PAUSE_SECONDS)
        self._calls += 1
        # max_results=1, а не 0: деякі сервери arXiv на 0 відповідають помилкою
        params = {"search_query": query, "start": 0, "max_results": 1}
        if len(query) > POST_ABOVE:
            resp = get_with_retry(API_URL, method="POST", data=params, headers=HEADERS, timeout=60,
                                  pauses=RETRY_PAUSES, sleep=self.sleep)
        else:
            resp = get_with_retry(API_URL, params=params, headers=HEADERS, timeout=60,
                                  pauses=RETRY_PAUSES, sleep=self.sleep)
        return parse_total(resp.text)

    def fetch_series(self) -> list[SeriesResult]:
        ids = {k: share_id(k) for k in self.directions} | {f"group:{g}": group_id(g) for g in GROUPS}
        start = min(self.since(TOTAL_ID, "GLOBAL"), *(self.since(mid, "GLOBAL") for mid in ids.values()))
        months = months_between(start, self.today)
        budget = int(os.getenv("ARXIV_COUNTS_MAX_QUERIES", str(MAX_QUERIES)))
        per_month = 1 + len(ids)
        queries = {k: ph for k, (_, _, ph, _) in self.directions.items()} | \
                  {f"group:{g}": group_phrases(self.directions, g) for g in GROUPS}

        total = SeriesResult(metric_id=TOTAL_ID, region="GLOBAL")
        shares = {k: SeriesResult(metric_id=mid, region="GLOBAL") for k, mid in ids.items()}
        self.stop_reason = None
        used = 0

        # Місяць записується лише цілим: усі статті + усі напрями. Збій або вичерпаний
        # ліміт запитів - зупинка; зібрані місяці пишуться, решту дозбирає наступний запуск.
        for m in months:
            if used + per_month > budget:
                self.stop_reason = f"ліміт {budget} запитів за запуск; продовження з {m:%Y-%m} наступного разу"
                break
            _, last = month_bounds(m)
            partial = last >= self.today
            used += per_month
            try:
                n_all = self.count(build_query(m, None))
                if n_all == 0:
                    raise ValueError("arXiv повернув 0 статей - підозріло")
                ns = {k: self.count(build_query(m, ph)) for k, ph in queries.items()}
            except Exception as e:
                self.stop_reason = f"{m:%Y-%m}: {type(e).__name__}: {e}"
                break
            total.points.append((m, float(n_all)))
            total.extra[m] = {"period_end": last.isoformat(), "is_estimate": partial}
            for k, n in ns.items():
                shares[k].points.append((m, round(100.0 * n / n_all, 3)))
                shares[k].extra[m] = {"period_end": last.isoformat(), "is_estimate": partial,
                                      "numerator": float(n), "denominator": float(n_all)}

        if self.stop_reason:
            self.log.warning(f"Зупинка: {self.stop_reason}")
            if not total.points:                        # не зібрано жодного місяця - це помилка запуску
                for r in (total, *shares.values()):
                    r.error = self.stop_reason
        return [total, *shares.values()]


def phrase_report(month: date, count=None, sleep=time.sleep, only: str | None = None,
                  out=print) -> list[tuple[str, str, int]]:
    """Скільки статей місяця дає кожна фраза окремо - щоб знайти зашумлені фрази.
    Друкує рядок одразу після кожного запиту; при збої arXiv зупиняється з частковим результатом."""
    c = ArxivCounts.__new__(ArxivCounts)
    c.sleep, c._calls = sleep, 0
    count = count or c.count
    rows: list[tuple[str, str, int]] = []
    try:
        total = count(build_query(month, None))
        rows.append(("всього", "", total))
        out(f"Місяць {month:%Y-%m}, усіх статей ШІ: {total}")
        if not only or only == "stems":
            for w1, w2 in STEM_CHECKS:
                n1, n2 = count(build_query(month, [w1])), count(build_query(month, [w2]))
                rows += [("основа", w1, n1), ("основа", w2, n2)]
                out(f"основа        {n1:6} | {n2:6}  «{w1}» | «{w2}»")
            if only == "stems":
                return rows
        if only in (None, "groups"):
            for g, (ua, _) in GROUPS.items():
                n = count(build_query(month, group_phrases(DIRECTIONS, g)))
                rows.append((f"group:{g}", ua, n))
                out(f"{'ГРУПА ' + g:16} {n:6} {100 * n / total:6.2f} %  {ua}")
            if only == "groups":
                return rows
        for k, (_, _, phrases, _) in DIRECTIONS.items():
            if only and k != only:
                continue
            for lbl, ph in [("УСІ ФРАЗИ", phrases), *((label(p), [p]) for p in phrases)]:
                n = count(build_query(month, ph))
                rows.append((k, lbl, n))
                out(f"{k:16} {n:6} {100 * n / total:6.2f} %  {lbl}")
    except Exception as e:
        out(f"ЗУПИНЕНО після {len(rows)} рядків: {type(e).__name__}: {str(e)[:200]}")
    return rows


def custom_report(month: date, phrases: list[str], count=None, sleep=time.sleep,
                  out=print) -> list[tuple[str, int]]:
    """Скільки статей місяця дають довільні фрази (кандидати в напрями) - разом і окремо."""
    c = ArxivCounts.__new__(ArxivCounts)
    c.sleep, c._calls = sleep, 0
    count = count or c.count
    rows: list[tuple[str, int]] = []
    try:
        total = count(build_query(month, None))
        out(f"Місяць {month:%Y-%m}, усіх статей ШІ: {total}")
        for lbl, ph in [("УСІ ФРАЗИ", phrases), *((p, [p]) for p in phrases)]:
            n = count(build_query(month, ph))
            rows.append((lbl, n))
            out(f"кандидат {n:6} {100 * n / total:6.2f} %  {lbl}")
    except Exception as e:
        out(f"ЗУПИНЕНО після {len(rows)} рядків: {type(e).__name__}: {str(e)[:200]}")
    return rows


def probe(sleep=time.sleep) -> None:
    """Діагностика: які частини запиту arXiv приймає. Друкує статус кожного варіанта."""
    import requests
    m = date.today().replace(day=1)
    first, last = month_bounds(date(m.year - (m.month == 1), 12 if m.month == 1 else m.month - 1, 1))
    when = f"submittedDate:[{first:%Y%m%d}0000 TO {last:%Y%m%d}2359]"
    variants = [
        ("як у збирачі сигналів", "cat:cs.AI OR cat:cs.CL OR cat:cs.LG", 5),
        ("max_results=0", "cat:cs.AI", 0),
        ("max_results=1", "cat:cs.AI", 1),
        ("дужки", "(cat:cs.AI OR cat:cs.LG)", 1),
        ("дата", f"cat:cs.AI AND {when}", 1),
        ("дужки + дата", f"(cat:cs.AI OR cat:cs.LG) AND {when}", 1),
        ("фраза в анотації", 'cat:cs.AI AND abs:"AI agent"', 1),
        ("повний запит", build_query(first, None), 1),
    ]
    for name, q, mx in variants:
        try:
            r = requests.get(API_URL, params={"search_query": q, "start": 0, "max_results": mx},
                             headers=HEADERS, timeout=60)
            extra = parse_total(r.text) if r.ok else r.text[:150].replace("\n", " ")
            print(f"{r.status_code}  {name:24} {extra}")
        except Exception as e:
            print(f"ERR  {name:24} {type(e).__name__}: {e}")
        sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        probe()
    elif "--check" in sys.argv:
        t = date.today()
        prev = date(t.year - (t.month == 1), 12 if t.month == 1 else t.month - 1, 1)
        custom = [x.strip() for x in os.getenv("PHRASE_CHECK_PHRASES", "").split(";") if x.strip()]
        if custom:
            custom_report(prev, custom)
        else:
            phrase_report(prev, only=os.getenv("PHRASE_CHECK_DIRECTION") or None)
    else:
        ArxivCounts().run()
