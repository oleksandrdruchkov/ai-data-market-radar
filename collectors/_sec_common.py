"""Спільна логіка збирачів SEC EDGAR (без залежності від core - тестується окремо).

Джерело: офіційні безкоштовні API SEC (data.sec.gov). Ключ не потрібен,
але SEC вимагає User-Agent з контактом: змінна середовища SEC_USER_AGENT,
наприклад "Skynet radar your@email". Ліміт SEC - 10 запитів/с; ми робимо
кілька десятків запитів за запуск з паузою.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

from core.http import get_with_retry

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/"

SEEDS = Path(__file__).parent / "seeds" / "market_companies.json"

# Показник -> XBRL-поняття US-GAAP у порядку пріоритету
METRICS: dict[str, list[str]] = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "rnd": ["ResearchAndDevelopmentExpense",
            "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "net_income": ["NetIncomeLoss"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}
INSTANT_METRICS = {"cash"}          # залишок на дату, а не потік за період
SINCE = date.fromisoformat(os.getenv("SEC_BACKFILL_START", "2021-01-01"))

# Щоденний запуск бере лише подання за останні N днів: історія вже в базі,
# а повторне проходження тисяч старих записів займало ~30 хв. 0 = повне завантаження з SINCE.
RECENT_DAYS = int(os.getenv("SEC_RECENT_DAYS", "45"))


def recent_cutoff(today: date | None = None, days: int | None = None) -> date:
    days = RECENT_DAYS if days is None else days
    if days <= 0:
        return SINCE
    return max(SINCE, (today or date.today()) - timedelta(days=days))


QUARTER_MIN, QUARTER_MAX = 80, 100  # тривалість кварталу в днях

# Форми, що цікавлять радар
FILING_FORMS = {
    "S-1": "ipo", "S-1/A": "ipo", "F-1": "ipo", "F-1/A": "ipo",
    "424B4": "ipo_pricing", "424B1": "ipo_pricing",
    "S-3": "follow_on", "S-3ASR": "follow_on", "424B2": "follow_on", "424B5": "follow_on",
    "10-Q": "periodic", "10-K": "periodic", "20-F": "periodic",
    "8-K": "event", "6-K": "event",
    "SC 13D": "ownership", "SC 13D/A": "ownership", "SC 13G": "ownership", "SC 13G/A": "ownership",
    "SCHEDULE 13D": "ownership", "SCHEDULE 13D/A": "ownership",
    "SCHEDULE 13G": "ownership", "SCHEDULE 13G/A": "ownership",
    "DEF 14A": "governance",
    # Форма 4 (угоди інсайдерів) свідомо не збирається: ~3/4 усіх подань великих компаній,
    # а сигнал слабкий. Стара історія лишається в таблиці з category = insider.
}

# Пункти 8-K, важливі для радара (офіційна нумерація форми 8-K)
EIGHT_K_ITEMS = {
    "1.01": "суттєва угода",
    "1.05": "суттєвий кіберінцидент",
    "2.01": "завершення придбання/продажу активів",
    "2.02": "фінансові результати",
    "2.03": "нове фінансове зобов'язання",
    "2.05": "витрати на вихід/реструктуризацію",
    "3.02": "продаж акцій без реєстрації",
    "5.01": "зміна контролю",
    "5.02": "зміни керівництва чи ради",
    "5.03": "зміни статуту",
    "5.07": "голосування акціонерів",
    "7.01": "розкриття за Reg FD",
    "8.01": "інші події",
}


@dataclass(frozen=True)
class Company:
    ticker: str
    name_must_contain: str
    label: str
    role: str
    note: str = ""


def load_companies(path: Path = SEEDS) -> list[Company]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Company(**c) for c in data["companies"]]


class SecClient:
    def __init__(self, user_agent: str | None = None, pause: float = 0.2):
        ua = user_agent or os.environ.get("SEC_USER_AGENT")
        if not ua or "@" not in ua:
            raise RuntimeError("SEC_USER_AGENT має містити назву і контактний e-mail (вимога SEC)")
        self.headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
        self.pause = pause

    def get_json(self, url: str) -> dict | None:
        """GET з повторами каркаса (429/5xx/обрив). 404 = у компанії немає таких даних."""
        time.sleep(self.pause)   # ліміт SEC - 10 запитів/с
        try:
            return get_with_retry(url, headers=self.headers, timeout=60).json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None
            raise


def resolve_ciks(tickers_json: dict, companies: list[Company]) -> tuple[dict[str, int], list[str]]:
    """Тикер -> CIK з перевіркою назви. Повертає (знайдені, пропущені з причиною)."""
    by_ticker = {v["ticker"].upper(): v for v in tickers_json.values()}
    found, skipped = {}, []
    for c in companies:
        row = by_ticker.get(c.ticker.upper())
        if row is None:
            skipped.append(f"{c.ticker}: ще немає в реєстрі SEC (не лістингована)")
        elif c.name_must_contain.upper() not in row["title"].upper():
            skipped.append(f"{c.ticker}: тикер належить '{row['title']}', не '{c.name_must_contain}'")
        else:
            found[c.ticker] = int(row["cik_str"])
    return found, skipped


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _latest_by_period(entries: list[dict], instant: bool) -> dict[tuple, dict]:
    """Один запис на період; при повторах (порівняльні дані, перерахунки) - найпізніше поданий."""
    out: dict[tuple, dict] = {}
    for e in entries:
        if e.get("form") not in ("10-Q", "10-K", "20-F", "10-K/A", "10-Q/A", "20-F/A"):
            continue
        key = (e["end"],) if instant else (e.get("start"), e["end"])
        if not instant and not e.get("start"):
            continue
        if key not in out or e["filed"] > out[key]["filed"]:
            out[key] = e
    return out


def quarterly_series(entries: list[dict], instant: bool = False) -> list[dict]:
    """Квартальний ряд з фактів XBRL.

    У звіті про рух грошей 10-Q подає накопичувальні суми з початку року (6, 9 міс.),
    а 10-K - за рік. Квартал = пряме значення (80-100 днів), або різниця двох
    накопичувальних сум з однаковою датою початку, що відрізняються на один квартал.
    """
    facts = _latest_by_period(entries, instant)
    rows: dict[str, dict] = {}

    if instant:
        for (end,), e in facts.items():
            if _d(end) >= SINCE:
                rows[end] = dict(period_type="instant", period_start=None, period_end=end, value=e["val"],
                                 derived=False, form=e["form"], accn=e["accn"], filed=e["filed"])
        return sorted(rows.values(), key=lambda r: r["period_end"])

    for (start, end), e in facts.items():
        days = (_d(end) - _d(start)).days
        if QUARTER_MIN <= days <= QUARTER_MAX and _d(end) >= SINCE:
            rows[end] = dict(period_start=start, period_end=end, value=e["val"], derived=False,
                             form=e["form"], accn=e["accn"], filed=e["filed"])

    annual: dict[str, dict] = {}
    for (start, end), e in facts.items():
        days = (_d(end) - _d(start)).days
        if 350 <= days <= 380 and _d(end) >= SINCE:
            annual[end] = dict(period_type="year", period_start=start, period_end=end, value=e["val"],
                               derived=False, form=e["form"], accn=e["accn"], filed=e["filed"])

    for (start, end), e in facts.items():
        if end in rows or _d(end) < SINCE:
            continue
        for (s2, e2), prev in facts.items():
            gap = (_d(end) - _d(e2)).days
            if s2 == start and QUARTER_MIN <= gap <= QUARTER_MAX:
                rows[end] = dict(period_start=(_d(e2) + timedelta(days=1)).isoformat(), period_end=end,
                                 value=e["val"] - prev["val"], derived=True,
                                 form=e["form"], accn=e["accn"], filed=e["filed"])
                break
    for r in rows.values():
        r["period_type"] = "quarter"
    return sorted(list(rows.values()) + list(annual.values()),
                  key=lambda r: (r["period_type"], r["period_end"]))


def extract_metrics(company_facts: dict) -> list[dict]:
    """Усі показники METRICS з companyfacts. Перше поняття зі списку, яке має дані, перемагає
    для кожного періоду; наступні лише заповнюють прогалини (компанії змінюють поняття з роками)."""
    gaap = (company_facts.get("facts") or {}).get("us-gaap") or {}
    out = []
    for metric, concepts in METRICS.items():
        chosen: dict[tuple, dict] = {}
        for concept in concepts:
            units = (gaap.get(concept) or {}).get("units") or {}
            # Більшість звітує в USD; іноземні емітенти (Alibaba) - у своїй валюті
            currency = "USD" if "USD" in units else next(iter(units), None)
            if currency is None:
                continue
            for row in quarterly_series(units[currency], instant=metric in INSTANT_METRICS):
                key = (row["period_type"], row["period_end"])
                if key not in chosen:
                    chosen[key] = {**row, "metric": metric, "xbrl_concept": concept, "currency": currency}
        out.extend(sorted(chosen.values(), key=lambda r: (r["period_type"], r["period_end"])))
    return out


def recent_filings(submissions: dict, since: date = SINCE) -> list[dict]:
    """Список подань з submissions API, лише форми з FILING_FORMS."""
    rec = (submissions.get("filings") or {}).get("recent") or {}
    n = len(rec.get("accessionNumber", []))
    out = []
    for i in range(n):
        form = rec["form"][i]
        category = FILING_FORMS.get(form)
        if category is None or _d(rec["filingDate"][i]) < since:
            continue
        items_raw = (rec.get("items") or [""] * n)[i] or ""
        items = [x.strip() for x in items_raw.split(",") if x.strip()]
        out.append(dict(
            accn=rec["accessionNumber"][i],
            form=form,
            category=category,
            filed=rec["filingDate"][i],
            report_date=(rec.get("reportDate") or [""] * n)[i] or None,
            primary_doc=(rec.get("primaryDocument") or [""] * n)[i] or None,
            description=(rec.get("primaryDocDescription") or [""] * n)[i] or None,
            items=items,
            items_labels=[EIGHT_K_ITEMS[x] for x in items if x in EIGHT_K_ITEMS],
        ))
    return out


def filing_url(cik: int, accn: str) -> str:
    return FILING_INDEX_URL.format(cik=cik, accn_nodash=accn.replace("-", ""))
