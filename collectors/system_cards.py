"""
collectors/system_cards.py
Системні картки моделей-лідерів -> fct_leader_action_rates (коло «у межах / поза межами»).

Що робить щодня:
  1. переглядає покажчики карток Anthropic і OpenAI, бере нові (ще не оброблені) документи;
  2. завантажує документ (PDF або HTML), відбирає сторінки про дії в реальній роботі;
  3. модель A витягує записи: модель, метод, кількості, цитати, сторінки; зберігаються лише
     записи реального використання (internal_use_sample) - симуляції й тести відкидаються;
  4. модель B (інша) витягує те саме незалежно - «друга думка»;
  5. код перевіряє кожен запис (collectors/_card_verify.py) і підтверджує автоматично
     лише те, що пройшло всі умови; решта чекає на людину й на коло не потрапляє.
Записи, які людина вже підтвердила вручну, збирач не перезаписує.

Змінні: CARDS_SINCE=2026-01-01   CARDS_MAX_PER_RUN=3   CARDS_SECOND_MODEL (за замовчуванням друга в каскаді)
Запуск: python -m collectors.system_cards
"""

from __future__ import annotations

import io
import os
import re
from datetime import date
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin

import requests
from pydantic import BaseModel, Field, field_validator

from core import BaseCollector, RawItem, Skip
from core.db import iso, utcnow
from collectors._card_verify import check_record, counts_as_out, match_second_opinion, severity_of
from core.review import REAL_METHOD

HEADERS = {"User-Agent": "MarketRadarBot/2.0 (+https://github.com/oleksandrdruchkov/ai-data-market-radar)"}
PROMPT_VERSION = "card_actions_v4"   # v4: лише реальне використання, без симуляцій
PROCESSING_VERSION = f"{PROMPT_VERSION}/pages_v3/units_v2/verify_v4"   # змінилась - документи переглядаються знову

# Картка = посилання, в тексті якого (або в рядку поруч) є «system card». Вигляд адреси не важливий:
# нові картки Anthropic мають у назві файлу пробіли й «&» або лежать на інших адресах.
INDEXES = [
    {"lab": "Anthropic", "url": "https://www.anthropic.com/system-cards",
     "link": r".", "title_must": "system card"},
    {"lab": "OpenAI", "url": "https://deploymentsafety.openai.com/",
     "link": r"^(?:https://deploymentsafety\.openai\.com)?/[a-z0-9-]+/?$", "title_must": "system card"},
]
_SKIP_HREF = ("#", "mailto:", "javascript:")

# Вага фрази: що специфічніша для «реальна робота + дії поза межами», то більша.
# Загальні слова (instruction, credentials) не використовуються - вони є на кожній сторінці.
KEYWORDS = {
    "day-to-day": 5, "internal use": 5, "internal usage": 5, "internal deployment": 4,
    "deployment simulation": 5, "real traffic": 4, "production traffic": 4, "resampl": 3,
    "works around": 4, "work around": 3, "circumvent": 3, "beyond the scope": 4, "beyond the user": 4,
    "beyond what the user": 4, "destructive": 2, "reckless": 2, "overeager": 2, "over-eager": 2,
    "overly agentic": 3, "severity 3": 4, "severity-3": 4, "without authorization": 3,
    "unauthorized": 2, "not authorized": 2, "transcripts": 1,
}
MAX_PAGES, MAX_CHARS = 60, 260_000


# ---------------- покажчики ----------------

class _Links(HTMLParser):
    """Посилання разом із коротким текстом перед ним (назва моделі в рядку таблиці чи пункті списку)."""

    BLOCKS = ("tr", "li", "article", "div", "p", "section", "h2", "h3")

    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self._href, self._text, self._recent = None, [], []

    SKIP = ("script", "style", "noscript", "template")

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip = getattr(self, "_skip", 0) + 1
        if tag in ("tr", "li", "article"):
            self._recent = []
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in self.SKIP and getattr(self, "_skip", 0):
            self._skip -= 1
        if tag == "a" and self._href:
            context = " ".join(self._recent[-6:])[-160:]
            self.links.append({"href": self._href, "text": " ".join(self._text).strip(),
                               "context": context.strip()})
            self._href, self._recent = None, []

    def handle_data(self, data):
        d = data.strip()
        if not d or getattr(self, "_skip", 0):
            return
        if self._href:
            self._text.append(d)
        else:
            self._recent.append(d)


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def listed_date(text: str) -> str | None:
    """'Oct 30, 2026' -> '2026-10-30'; 'September 2026' -> '2026-09-01'; інакше None."""
    t = (text or "").lower()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),\s*(20\d\d)", t)
    if m:
        return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d\d)", t)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}-01"
    return None


def discover(index: dict, html: str) -> list[dict]:
    """Документи з покажчика, від нових до старих (покажчики самі не завжди так відсортовані)."""
    p = _Links()
    p.feed(html)
    seen, out = set(), []
    for ln in p.links:
        href = (ln["href"] or "").strip()
        if not href or href.startswith(_SKIP_HREF) or not re.search(index["link"], href):
            continue
        both = " ".join(x for x in (ln["context"], ln["text"]) if x).strip()
        if index.get("title_must") and index["title_must"] not in both.lower():
            continue
        url = urljoin(index["url"], href)
        if url.rstrip("/") == index["url"].rstrip("/") or url in seen:
            continue
        seen.add(url)
        text = ln["text"].strip()
        # «GPT-6 Cyber System Card» - змістовна назва; «Read system card» - ні, тоді беремо рядок таблиці
        title = text if len(text) > 18 and text.lower() not in ("read system card", "system card") else both
        out.append({"lab": index["lab"], "url": url, "title": title[:300], "listed_date": listed_date(both)})
    return sorted(out, key=lambda d: d["listed_date"] or "0000", reverse=True)


def linked_cards(index: dict, html: str, base_url: str) -> list[str]:
    """Посилання на інші картки всередині картки (основна картка GPT-6 є лише в доповненнях)."""
    p = _Links()
    p.feed(html)
    urls = []
    for ln in p.links:
        href = (ln["href"] or "").strip()
        if re.search(index["link"], href) and "system card" in (ln["text"] + " " + ln["context"]).lower():
            u = urljoin(base_url, href).rstrip("/")
            if u != base_url.rstrip("/") and u not in urls:
                urls.append(u)
    return urls


# ---------------- документ ----------------

def http_get(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    return resp


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("p", "li", "tr", "h1", "h2", "h3", "h4", "br", "div", "td"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def document_pages(content: bytes, content_type: str) -> dict[str, str]:
    """{'номер сторінки': текст}. PDF - справжні сторінки; HTML - частини по ~4000 знаків."""
    if "pdf" in content_type or content[:4] == b"%PDF":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return {str(i + 1): (pg.extract_text() or "") for i, pg in enumerate(reader.pages)}
    p = _Text()
    p.feed(content.decode("utf-8", errors="replace"))
    text = re.sub(r"\n\s*\n+", "\n", "".join(p.parts))
    pages, buf, n = {}, [], 1
    for line in text.split("\n"):
        buf.append(line)
        if sum(len(b) for b in buf) > 4000:
            pages[str(n)] = "\n".join(buf); buf, n = [], n + 1
    if buf:
        pages[str(n)] = "\n".join(buf)
    return pages


# Фрази, що позначають саме дані реальної роботи. Сторінки з ними (і сусідні) беруться завжди й першими.
ANCHORS = ("day-to-day", "internal use", "internal usage", "internal deployment", "deployment simulation",
           "real traffic", "production traffic", "resampled", "resampling")


def relevant_pages(pages: dict[str, str]) -> dict[str, str]:
    """1) сторінки з фразами про реальну роботу і 5 наступних; 2) решта місця - сторінки про поведінку за вагою."""
    def score(t: str) -> int:
        low = t.lower()
        return sum(w * low.count(phrase) for phrase, w in KEYWORDS.items())

    nums = sorted(int(k) for k in pages)
    anchors = [n for n in nums if any(a in pages[str(n)].lower() for a in ANCHORS)]
    # розділ про реальну роботу триває кілька сторінок (у Mythos 5: стор. 37-42) - беремо вікно
    window = {}
    for n in anchors:
        for m in range(n - 1, n + 6):
            if str(m) in pages:
                window.setdefault(m, abs(m - n))
    first = sorted(window, key=lambda m: (window[m], -score(pages[str(m)])))
    rest = sorted((n for n in nums if n not in first and score(pages[str(n)]) > 0),
                  key=lambda n: -score(pages[str(n)]))
    out, total = {}, 0
    for n in first + rest:
        t = pages[str(n)]
        if len(out) >= MAX_PAGES or total + len(t) > MAX_CHARS:
            continue
        out[str(n)] = t; total += len(t)
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


# ---------------- схема відповіді моделі ----------------

UNIT_SYNONYMS = {
    "use": "use", "uses": "use", "usage": "use", "day to day use": "use", "session": "session",
    "sessions": "session", "turn": "turn", "turns": "turn", "response": "turn", "responses": "turn",
    "completion": "turn", "completions": "turn", "conversation turn": "turn",
    "tool call": "tool_call", "tool_call": "tool_call", "tool calls": "tool_call", "action": "tool_call",
    "actions": "tool_call", "trajectory": "trajectory", "trajectories": "trajectory", "episode": "trajectory",
    "rollout": "trajectory", "transcript": "transcript", "transcripts": "transcript",
    "task": "task", "tasks": "task", "conversation": "conversation", "conversations": "conversation",
}


class CardItem(BaseModel):
    category: str = Field(min_length=3, max_length=200)
    is_action: bool                      # True - дія поза межами; False - неправдивий звіт тощо
    n: int | None = Field(default=None, ge=0)
    rate_percent: float | None = Field(default=None, ge=0, le=100)
    severity: int | None = Field(default=None, ge=0, le=4)   # рівень за шкалою картки, якщо вона є
    page: str
    quote: str = Field(min_length=10, max_length=600)


class CardRecord(BaseModel):
    model_name: str = Field(min_length=2, max_length=80)
    method: Literal["internal_use_sample", "deployment_simulation"]
    unit: str = Field(default="use", max_length=40)

    @field_validator("unit", mode="before")
    @classmethod
    def _unit(cls, v):
        """Одиниця потрібна лише для підпису: приймаємо будь-яку, знайомі синоніми зводимо до стандартних."""
        u = re.sub(r"[^a-z_ -]", "", str(v or "use").lower()).strip().replace("-", " ")
        return UNIT_SYNONYMS.get(u, u.replace(" ", "_") or "use")
    n_total: int | None = Field(default=None, gt=0)
    n_total_quote: str | None = None
    n_total_page: str | None = None
    classifier: str | None = Field(default=None, max_length=200)
    section: str | None = Field(default=None, max_length=120)
    items: list[CardItem] = Field(min_length=1, max_length=20)


class CardExtraction(BaseModel):
    document_date: str | None = None     # YYYY-MM-DD
    records: list[CardRecord] = Field(default_factory=list, max_length=6)


def build_prompt(lab: str, title: str, pages: dict[str, str]) -> str:
    body = "\n\n".join(f"=== PAGE {k} ===\n{v}" for k, v in pages.items())
    return f"""You read an AI developer's system card ({lab}: {title}). Extract ONLY measurements of how often
the model takes actions BEYOND THE BOUNDS of its task in REAL usage.

Allowed data (method):
- "internal_use_sample": a sample of the model's REAL, day-to-day use where the model itself did the work
  (e.g. internal Claude Code use by employees, real deployment transcripts of THIS model).
NOT allowed - return nothing for them: deployment simulations or re-generation/resampling of recorded traffic
with the new model, constructed scenarios, red-teaming, honeypots, synthetic environments,
"trap" tests built to provoke misbehavior, capability benchmarks.

For each category of behavior in the allowed data, add an item:
- is_action = true: an action the task did not provide for - bypassing/working around a block or restriction,
  destructive actions, using credentials or permissions not granted, acting on resources the user did not name,
  ignoring an explicit prohibition by DOING something.
- is_action = false: false or unverified REPORTS about the work (claiming done/verified when not, guesses stated
  as fact, invented details) - these are statements, not actions.
- If the card grades behaviors on a SEVERITY scale (e.g. 0-4), add ONE item per severity level or per row of the
  card's table (and per category if given), with "severity" = that level; for a row covering a range
  ("severity 3 or higher", "severity 1 or 2") use the LOWEST level of the range and keep the row's wording in
  "category". Never merge rows and never report "any severity" totals as one item.
  If there is no severity scale, severity = null.
- n = count, or rate_percent = percentage (as printed, e.g. 0.251 for "0.251%"). Only numbers printed in the TEXT;
  if a number is only visible in a chart/figure, leave it null.
- page = the page number shown in "=== PAGE k ===" where the quote is.
- quote = an EXACT copy of a sentence/row from that page containing the number. Do not paraphrase.
n_total = total number of uses/turns in the sample, with n_total_quote copied exactly and n_total_page.
model_name = the evaluated model as named in the card. document_date = the card's publication date (YYYY-MM-DD).
If there is no allowed data, return {{"document_date": ..., "records": []}}.

Return strictly valid JSON for this schema:
{{"document_date": "YYYY-MM-DD", "records": [{{"model_name": "...", "method": "internal_use_sample",
 "unit": "use|turn|tool_call|trajectory", "n_total": 886, "n_total_quote": "...", "n_total_page": "37",
 "classifier": "who classified the behaviors", "section": "2.3.3",
 "items": [{{"category": "...", "is_action": true, "severity": null, "n": 9, "rate_percent": null, "page": "40", "quote": "..."}}]}}]}}

{body}
"""


# ---------------- збирач ----------------

class SystemCards(BaseCollector):
    source = "system_cards"
    fact_table = "fct_leader_action_rates"
    id_column = ""
    collection_method = "scrape"
    tracks_presence = False
    allow_empty = True
    reprocess_limit = 3
    collector_version = "1"

    def fetch(self):
        since = os.getenv("CARDS_SINCE", "2026-01-01")
        max_new = int(os.getenv("CARDS_MAX_PER_RUN", "3"))
        docs_tbl = self.db.select("ops_documents", "url,lab,title,status,processed_version,listed_date")
        done = {r["url"] for r in docs_tbl if r["processed_version"] == PROCESSING_VERSION
                and r["status"] != "queued"}
        queued = [r for r in docs_tbl if r["status"] == "queued"]
        for idx in INDEXES:
            try:
                docs = discover(idx, http_get(idx["url"]).text)
            except Exception as e:
                docs = []
                self.log.warning(f"Покажчик {idx['lab']} недоступний: {e}")
            self.log.info(f"{idx['lab']}: у покажчику {len(docs)} документів")
            if not docs:   # сторінка змінилась або недоступна - це треба бачити на табло стану
                self.db.insert_alerts([{"source": self.source, "check_name": "index_empty", "severity": "warning",
                                        "message": f"Покажчик карток {idx['lab']} не дав жодного документа: {idx['url']}"}])
            fresh = []
            for d in docs:
                if d["url"] in done:
                    continue
                if d["listed_date"] and d["listed_date"] < since:      # старі - навіть не завантажуємо
                    self._mark(d, "no_real_use_data", note=f"старий документ за покажчиком ({d['listed_date']})")
                    continue
                fresh.append(d)
            known = {d["url"] for d in fresh}
            fresh += [{"lab": q["lab"], "url": q["url"], "title": q["title"], "listed_date": q["listed_date"]}
                      for q in queued if q["lab"] == idx["lab"] and q["url"] not in known and q["url"] not in done]
            for d in fresh[:max_new]:
                yield RawItem(external_id=d["url"], payload={**d, "since": since}, content_key=d["url"])

    def _mark(self, d: dict, status: str, n: int = 0, note: str | None = None):
        self.db.upsert("ops_documents", {"url": d["url"], "lab": d["lab"], "title": d.get("title"),
                                         "listed_date": d.get("listed_date"),
                                         "status": status, "n_records": n, "note": note,
                                         "processed_version": PROCESSING_VERSION,
                                         "processed_at": iso(utcnow())}, on_conflict="url")

    def _queue_links(self, d: dict, html: str):
        idx = next((i for i in INDEXES if i["lab"] == d["lab"]), None)
        if not idx:
            return
        known = {r["url"] for r in self.db.select("ops_documents", "url")}
        new = [u for u in linked_cards(idx, html, d["url"]) if u not in known]
        for u in new:
            self.db.upsert("ops_documents", {"url": u, "lab": d["lab"], "title": None, "status": "queued",
                                             "note": f"знайдено в {d['url']}"}, on_conflict="url",
                           ignore_duplicates=True)
        if new:
            self.log.info(f"У черзі нові картки з {d['url']}: {new}")

    def parse(self, raw: RawItem) -> dict | None:
        d = raw.payload
        resp = http_get(d["url"])
        ctype = resp.headers.get("content-type", "")
        pages = document_pages(resp.content, ctype)
        if "html" in ctype:
            try:    # черга - допоміжна річ: її збій не має зривати обробку самої картки
                self._queue_links(d, resp.content.decode("utf-8", errors="replace"))
            except Exception as e:
                self.log.warning(f"Не вдалося поставити посилання в чергу ({d['url']}): {e}")
        rel = relevant_pages(pages)
        sent = f"сторінок у документі: {len(pages)}; передано моделі: {','.join(rel) or '—'}"
        if not rel:
            self._mark(d, "no_relevant_pages", note=sent); raise Skip("немає сторінок про дії")

        prompt = build_prompt(d["lab"], d.get("title", ""), rel)
        first = self.llm.extract(prompt=prompt, schema=CardExtraction, prompt_name="card_actions",
                                 prompt_version=PROMPT_VERSION, content_hash=raw.content_hash, temperature=0.0)
        if first is None:
            return None                                           # відкласти до наступного запуску
        # Лише реальне використання: якщо модель усе ж повернула симуляцію - відкидаємо тут, кодом
        first.data.records = [r for r in first.data.records if r.method == REAL_METHOD]
        doc_date = (first.data.document_date or "")[:10]
        if doc_date and doc_date < d.get("since", "2026-01-01"):
            self._mark(d, "no_real_use_data", note=f"старий документ {doc_date}; {sent}"); raise Skip("старий документ")
        if not first.data.records:
            self._mark(d, "no_real_use_data", note=sent); raise Skip("немає даних реальної роботи")
        self._sent_note = sent

        # друга думка: будь-яка ІНША модель каскаду (якщо одна вичерпала квоту - наступна)
        others = ([os.getenv("CARDS_SECOND_MODEL")] if os.getenv("CARDS_SECOND_MODEL")
                  else [m for m in self.llm.models if m != first.model])
        second = (self.llm.extract(prompt=prompt, schema=CardExtraction, prompt_name="card_actions_2nd",
                                   prompt_version=PROMPT_VERSION, content_hash=raw.content_hash,
                                   temperature=0.0, models=others)
                  if others else None)
        if second is not None and second.model == first.model:     # на всяк випадок: та сама модель - не друга думка
            second = None
        other = [r.model_dump() for r in second.data.records if r.method == REAL_METHOD] if second else []

        min_sev = int(os.getenv("CARDS_MIN_SEVERITY", "3"))
        rows = []
        for rec in first.data.records:
            r = rec.model_dump()
            ok, log, rate, n_out = check_record(r, pages, min_sev)
            if second is None:
                agree, why = False, "друга модель недоступна"
            else:
                agree, why = match_second_opinion(r, other, min_sev)
            log.append(why)
            if rate is None:
                rate = 0.0                                         # рядок лишиться непідтвердженим
            auto = ok and agree
            acts = [it for it in r["items"] if counts_as_out(it, min_sev)]
            rows.append({
                "lab": d["lab"], "model_name": r["model_name"],
                "release_date": doc_date or date.today().isoformat(),
                "source_doc": d.get("title") or d["url"], "source_url": d["url"],
                "section": r.get("section"), "page": ", ".join(sorted({it["page"] for it in acts})),
                "method": r["method"], "unit": r["unit"], "classifier": r.get("classifier"),
                "n_total": r.get("n_total"), "n_out": n_out, "rate_out": rate,
                "counted": [{"category": it["category"], "severity": severity_of(it), "n": it["n"],
                             "rate": (it["rate_percent"] / 100 if it["rate_percent"] is not None else None),
                             "page": it["page"], "quote": it["quote"]} for it in acts],
                "excluded": [{"category": it["category"], "severity": severity_of(it), "n": it["n"],
                              "page": it["page"],
                              "why": ("неправдивий звіт, не дія" if not it["is_action"]
                                      else f"рівень серйозності {severity_of(it)} нижче порогу {min_sev}")}
                             for it in r["items"] if not counts_as_out(it, min_sev)],
                "evidence_quote": r.get("n_total_quote"),
                "data_origin": "primary_text",
                "verified": auto, "verified_by": "auto" if auto else None,
                "verified_at": iso(utcnow()) if auto else None,
                "verification_log": log,
                "extraction_method": f"{first.method} + {second.method if second else '—'}",
                "notes": None if auto else "Автоматична перевірка не пройдена - див. verification_log.",
            })
        return {"_rows": rows, "extraction_method": first.method, "prompt_version": PROMPT_VERSION}

    def _delete_pending(self, url: str) -> None:
        self.db.delete(self.fact_table, eq={"source_url": url, "verified": False}, is_null=("verified_by",))

    def save(self, fact: dict, raw: RawItem, raw_id: int) -> None:
        rows = fact["_rows"]
        human = {(r["lab"], r["model_key"], r["source_url"], r["method"])
                 for r in self.db.select(self.fact_table, "lab,model_key,source_url,method",
                                         eq={"verified_by": "human"})}
        keep, seen = [], set()
        for r in rows:
            key = (r["lab"], model_key(r["model_name"]), r["source_url"], r["method"])
            if key in human or key in seen:      # ручне підтвердження не перезаписуємо; дубль у відповіді - один
                continue
            seen.add(key)
            keep.append(dict(r, raw_item_id=raw_id))
        # документ переглянуто заново: його попередні НЕпідтверджені автоматичні записи вже не актуальні
        self._delete_pending(raw.payload["url"])
        if keep:
            self.db.upsert(self.fact_table, keep, on_conflict="lab,model_key,source_url,method")
        pending = sum(1 for r in keep if not r["verified"])
        if pending:
            self.db.insert_alerts([{"source": self.source, "check_name": "pending_human_review", "severity": "info",
                                    "message": f"{pending} запис(и) з {raw.payload['url']} не пройшли автоперевірку"}])
        self._mark(raw.payload, "done", len(keep), note=getattr(self, "_sent_note", None))


def model_key(name: str) -> str:
    """Той самий ключ, що й radar_model_key() у SQL: 'GPT-6-Cyber' -> 'gpt 6 cyber'."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


if __name__ == "__main__":
    SystemCards().run()
