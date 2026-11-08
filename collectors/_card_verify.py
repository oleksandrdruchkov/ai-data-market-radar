"""
collectors/_card_verify.py
Механічна перевірка записів, витягнутих моделлю з системних карток.
Тут немає жодної моделі: лише порівняння тексту й арифметика. Саме цей код вирішує,
чи запис підтверджується автоматично (verified_by = 'auto'), чи чекає на людину.

Запис підтверджується, лише якщо ВСІ умови виконано:
  1. кожна цитата дослівно є на вказаній сторінці (допускається сусідня сторінка - перенос);
  2. кожне число (кількість або відсоток) є в самій цитаті;
  3. загальна кількість (n_total), якщо вказана, є в цитаті або на вказаній сторінці;
  4. є хоча б одна зарахована дія; частку рахує цей код, а не модель;
  5. друга, інша модель незалежно витягла ті самі числа й ту саму класифікацію дій.
Числа лише на графіках не проходять умову 2 і чекають на людину - так і має бути.
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
           "−": "-", " ": " ", " ": " ", " ": " "}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    for a, b in {**_LIGATURES, **_QUOTES}.items():
        t = t.replace(a, b)
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)        # перенос слова в кінці рядка PDF
    t = re.sub(r"\s+", " ", t)
    return t.strip().lower()


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _page_keys(page: str | None, pages: dict[str, str]) -> list[str]:
    """Вказана сторінка і сусідні (цитата могла перейти через межу сторінки)."""
    if not page:
        return list(pages)
    m = re.match(r"\s*(\d+)", str(page))
    if not m or m.group(1) not in pages:
        return [str(page)] if str(page) in pages else []
    n = int(m.group(1))
    return [k for k in (str(n - 1), str(n), str(n + 1)) if k in pages]


def _number_variants(value: float, is_percent: bool) -> list[str]:
    if not is_percent:
        return [str(int(value))] if float(value).is_integer() else [str(value)]
    s = f"{value:.6f}".rstrip("0").rstrip(".")
    out = {s, s.lstrip("0") if s.startswith("0.") else s}
    if "." in s:
        out.add(s.replace(".", ","))
    return sorted(out)


def _contains_number(text: str, value: float, is_percent: bool) -> bool:
    for v in _number_variants(value, is_percent):
        if re.search(rf"(?<![\d.,]){re.escape(v)}(?![\d])", text):
            return True
    return False


def check_record(rec: dict, pages: dict[str, str]) -> tuple[bool, list[str], float | None, int | None]:
    """Повертає (пройдено, журнал, частка, n_out). rec - запис у форматі схеми CardRecord (dict)."""
    log: list[str] = []
    norm_pages = {k: normalize(v) for k, v in pages.items()}
    ok = True

    actions = [it for it in rec.get("items", []) if it.get("is_action")]
    if not actions:
        return False, ["немає жодної зарахованої дії поза межами"], None, None

    for it in rec.get("items", []):
        label = f"«{it.get('category', '?')}»"
        keys = _page_keys(it.get("page"), norm_pages)
        quote = normalize(it.get("quote", ""))
        if len(quote) < 10:
            ok = False; log.append(f"{label}: цитата закоротка"); continue
        hay = " ".join(norm_pages[k] for k in keys)
        # порівнюємо без пробілів: PDF часто розриває слова й рядки, а сам текст той самий
        if not keys or _squash(quote) not in _squash(hay):
            ok = False; log.append(f"{label}: цитату не знайдено на стор. {it.get('page')}"); continue
        if it.get("n") is not None and not _contains_number(quote, it["n"], False):
            ok = False; log.append(f"{label}: число {it['n']} відсутнє в цитаті")
        if it.get("rate_percent") is not None and not _contains_number(quote, it["rate_percent"], True):
            ok = False; log.append(f"{label}: {it['rate_percent']}% відсутнє в цитаті (можливо, лише на графіку)")
        if it.get("n") is None and it.get("rate_percent") is None and it.get("is_action"):
            ok = False; log.append(f"{label}: немає ні кількості, ні відсотка")

    n_total = rec.get("n_total")
    if n_total is not None:
        keys = _page_keys(rec.get("n_total_page"), norm_pages) or list(norm_pages)
        where = normalize(rec.get("n_total_quote") or "") + " " + " ".join(norm_pages[k] for k in keys)
        if not _contains_number(where, n_total, False):
            ok = False; log.append(f"загальна кількість {n_total} не знайдена в документі")

    # частку рахує код
    rate, n_out = None, None
    if n_total and all(a.get("n") is not None for a in actions):
        n_out = sum(int(a["n"]) for a in actions)
        if n_out > n_total:
            ok = False; log.append(f"сума {n_out} більша за загальну кількість {n_total}")
        else:
            rate = n_out / n_total
    elif all(a.get("rate_percent") is not None for a in actions):
        rate = sum(float(a["rate_percent"]) for a in actions) / 100.0
    else:
        ok = False; log.append("неможливо порахувати частку: змішано кількості й відсотки")

    if rate is not None and not 0 <= rate <= 1:
        ok = False; log.append(f"частка {rate} поза межами 0..1"); rate = None
    if ok:
        log.append("цитати й числа знайдено в документі; частку пораховано кодом")
    return ok, log, rate, n_out


def _signature(rec: dict) -> tuple:
    acts = sorted((float(a["n"]) if a.get("n") is not None else -1.0,
                   round(float(a["rate_percent"]), 6) if a.get("rate_percent") is not None else -1.0)
                  for a in rec.get("items", []) if a.get("is_action"))
    return (rec.get("method"), rec.get("n_total"), tuple(acts))


def _model_key(name: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", (name or "").lower())


def match_second_opinion(rec: dict, other_records: list[dict]) -> tuple[bool, str]:
    """Чи друга модель витягла для тієї ж моделі й методу ті самі числа й класифікацію."""
    same = [o for o in other_records
            if _model_key(o.get("model_name")) == _model_key(rec.get("model_name"))
            and o.get("method") == rec.get("method")]
    if not same:
        return False, "друга модель не знайшла такого запису"
    if any(_signature(o) == _signature(rec) for o in same):
        return True, "друга модель витягла ті самі числа"
    return False, "друга модель витягла інші числа або іншу класифікацію дій"
