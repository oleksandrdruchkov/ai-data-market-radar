"""
metrics/funding_ladder.py
Драбина фінансування перегонів ШІ, версія v0 -> fct_metric_values (щомісяця).

Звідки компанії беруть гроші на будівництво обчислень - сходинки від безпечної до крихкої:
  0  власні кошти        капвитрати за 4 квартали <= грошовий потік від основної діяльності
  1  запаси              капвитрати > грошового потоку (різницю покривають накопиченим)
  2  борг               ЧИСТИЙ новий борг (залучено мінус погашено) >= DEBT_SHARE капвитрат за 4 квартали;
                         перекредитування старого боргу не рахується
  3  кредит постачальника системний сигнал з боку Nvidia: дебіторська заборгованість або запаси
                         відносно квартальної виручки зросли за рік більш ніж на VENDOR_RATIO_PCT %
                         (клієнти платять повільніше / попит слабшає)
  4  гроші населення     IPO (S-1, F-1, 424B4) за останні 365 днів або ЧИСТА емісія акцій
                         (продано мінус викуплено) >= EQUITY_SHARE капвитрат за 4 квартали
Сходинка компанії = найвища, умова якої виконана (сходинки не обов'язково проходять по черзі).

Публікується лише найвищий показник серед лабораторій-лідерів (role = 'lab'):
  funding_ladder_rung        найвища сходинка серед лабораторій, з урахуванням сходинки 3 (Nvidia)
  funding_ladder_capex_ocf   найвище відношення капвитрати / грошовий потік серед лабораторій
  funding_ladder_vendor_gap  Nvidia: найбільша зміна (дебіторка або запаси) / виручка за рік, %
Розрахунок по кожній компанії зберігається для перевірки (region = тикер), на табло не виводиться:
  funding_ladder_rung_company

Без знання майбутнього: на кожну дату беруться лише звіти з filed_date <= цієї дати.
Пороги - перша версія, не перевірені; змінюйте METHOD_VERSION при будь-якій зміні.

Запуск: python -m metrics.funding_ladder   (після collectors.sec_financials і sec_filings)
"""

from __future__ import annotations

import sys
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from core.db import Db

log = logging.getLogger("radar.metrics.funding_ladder")

RUN_LABEL = "metrics_funding_ladder"
METHOD_VERSION = "v0"
REGION_ALL = "GLOBAL"
START = date(2022, 1, 31)

DEBT_SHARE = 0.10        # борг >= 10 % капвитрат за 4 квартали
EQUITY_SHARE = 0.05      # емісія акцій >= 5 % капвитрат за 4 квартали
VENDOR_RATIO_PCT = 25.0  # Nvidia: (дебіторка або запаси) / виручка кварталу виросли за рік більш ніж на 25 %
IPO_WINDOW_DAYS = 365
MAX_TTM_SPAN_DAYS = 460  # 4 квартали мають вкладатися в ~15 місяців, інакше є діра у звітах
IPO_FORMS = {"S-1", "S-1/A", "F-1", "F-1/A", "424B4", "424B1"}
FLOWS = ("capex", "ocf", "debt_issued", "debt_repaid", "equity_issued", "buybacks", "revenue")

RUNG_LABELS = {0: ("own funds", "власні кошти"), 1: ("drawing reserves", "проїдають запаси"),
               2: ("debt", "борг"), 3: ("vendor credit", "кредит постачальника"),
               4: ("public money", "гроші населення")}


@dataclass
class Ttm:
    values: dict = field(default_factory=dict)   # metric -> сума за 4 квартали (або рік)
    asof_period: str | None = None


def ttm_asof(fin: pd.DataFrame, ticker: str, asof: date) -> Ttm | None:
    """Суми потоків за останні 4 квартали, відомі на дату asof. Для емітентів лише з річною
    звітністю (20-F) - останній рік. None, якщо даних недостатньо."""
    f = fin[(fin["ticker"] == ticker) & (fin["filed_date"] <= asof) & fin["metric"].isin(FLOWS)]
    if f.empty:
        return None
    out = Ttm()
    q = f[f["period_type"] == "quarter"]
    if not q.empty:
        ends = sorted(q["period_end"].unique())[-4:]
        if len(ends) == 4 and (ends[-1] - ends[0]).days <= MAX_TTM_SPAN_DAYS - 91:
            sub = q[q["period_end"].isin(ends)]
            for m in FLOWS:
                vals = sub[sub["metric"] == m]
                if len(vals) == 4:
                    out.values[m] = float(vals["value"].sum())
            out.asof_period = ends[-1].isoformat()
            return out
    y = f[f["period_type"] == "year"]
    if y.empty:
        return None
    last_end = y["period_end"].max()
    if (asof - last_end).days > 550:      # річний звіт старіший за ~1.5 року - не рахуємо
        return None
    sub = y[y["period_end"] == last_end]
    for m in FLOWS:
        vals = sub[sub["metric"] == m]
        if len(vals):
            out.values[m] = float(vals["value"].iloc[0])
    out.asof_period = last_end.isoformat()
    return out


def company_rung(ttm: Ttm | None, ipo_recent: bool) -> tuple[int | None, float | None]:
    """(сходинка, капвитрати/грошовий потік). Сходинка 3 - системна, рахується окремо."""
    if ipo_recent:
        rung = 4
    else:
        rung = None
    if ttm is None or "capex" not in ttm.values:
        return rung, None
    v = ttm.values
    capex = abs(v["capex"])
    ocf = v.get("ocf")
    ratio = capex / ocf if ocf and ocf > 0 else None
    r = 0
    if ocf is not None and (ocf <= 0 or capex > ocf):
        r = 1
    net_debt = v.get("debt_issued", 0) - abs(v.get("debt_repaid", 0))
    net_equity = v.get("equity_issued", 0) - abs(v.get("buybacks", 0))
    if capex > 0 and net_debt >= DEBT_SHARE * capex:
        r = 2
    if capex > 0 and net_equity >= EQUITY_SHARE * capex:
        r = 4
    if ocf is None and r == 0:
        return rung, ratio            # без грошового потоку сходинку 0 не стверджуємо
    return max(r, rung or 0), ratio


def _ratio_change(num: pd.DataFrame, rev: pd.DataFrame, asof: date) -> float | None:
    """Зміна відношення залишок / виручка кварталу за рік, %. Відношення, а не різниця темпів росту:
    при вибуховому рості виручки різниця темпів дає хибні сплески."""
    num = num[num["filed_date"] <= asof]
    rev = rev[rev["filed_date"] <= asof]
    if num.empty or rev.empty:
        return None
    ratios = {}
    for _, r in num.iterrows():
        m = rev[(rev["period_end"] - r["period_end"]).abs() <= pd.Timedelta(days=7)]
        if len(m) and float(m.iloc[0]["value"]) > 0:
            ratios[r["period_end"]] = float(r["value"]) / float(m.iloc[0]["value"])
    if not ratios:
        return None
    last = max(ratios)
    prev = [d for d in ratios if abs((last - timedelta(days=365) - d).days) <= 20]
    if not prev or ratios[prev[0]] == 0:
        return None
    return 100.0 * (ratios[last] / ratios[prev[0]] - 1.0)


def vendor_stress(fin: pd.DataFrame, asof: date, ticker: str = "NVDA") -> tuple[bool | None, float | None]:
    """(сигнал, найбільша зміна %). Дебіторка й запаси в днях виручки: якщо ростуть швидше
    за продажі - клієнти платять повільніше або склад затоварюється."""
    f = fin[fin["ticker"] == ticker]
    rev = f[(f["metric"] == "revenue") & (f["period_type"] == "quarter")]
    changes = []
    for m in ("receivables", "inventory"):
        c = _ratio_change(f[(f["metric"] == m) & (f["period_type"] == "instant")], rev, asof)
        if c is not None:
            changes.append(c)
    if not changes:
        return None, None
    worst = max(changes)
    return worst > VENDOR_RATIO_PCT, round(worst, 1)


def asof_dates(today: date, start: date = START) -> list[date]:
    out = [d.date() for d in pd.date_range(start, today, freq="ME")]
    if not out or out[-1] != today:
        out.append(today)
    return out


def build_rows(fin: pd.DataFrame, filings: pd.DataFrame, labs: list[str], today: date,
               run_id=None) -> list[dict]:
    rows = []
    for d in asof_dates(today):
        day = d.isoformat()
        rungs, ratios = {}, []
        for t in labs:
            ipo = filings[(filings["ticker"] == t) & filings["form"].isin(IPO_FORMS)
                          & (filings["filed_date"] <= d)
                          & (filings["filed_date"] > d - timedelta(days=IPO_WINDOW_DAYS))]
            rung, ratio = company_rung(ttm_asof(fin, t, d), not ipo.empty)
            if rung is not None:
                rungs[t] = rung
                rows.append(_row("funding_ladder_rung_company", day, t, rung, run_id))
            if ratio is not None:
                ratios.append(ratio)
        stress, gap = vendor_stress(fin, d)
        if not rungs:
            continue
        top = max(rungs.values())
        if stress:
            top = max(top, 3)
        r = _row("funding_ladder_rung", day, REGION_ALL, top, run_id)
        r["numerator"] = len(rungs)             # скільки лабораторій мали дані на цю дату
        r["denominator"] = len(labs)
        rows.append(r)
        if ratios:
            rows.append(_row("funding_ladder_capex_ocf", day, REGION_ALL, round(max(ratios), 3), run_id))
        if gap is not None:
            rows.append(_row("funding_ladder_vendor_gap", day, "US", gap, run_id))
    return rows


def _row(metric_id, day, region, value, run_id):
    return {"metric_id": metric_id, "period_start": day, "period_end": day, "region": region,
            "value": float(value), "is_estimate": False, "method_version": METHOD_VERSION, "run_id": run_id}


def _load(db: Db, table: str, columns: str) -> pd.DataFrame:
    data, offset = [], 0
    while True:
        page = db.table(table).select(columns).order("id").range(offset, offset + 999).execute().data or []
        data.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    df = pd.DataFrame(data)
    for c in ("filed_date", "period_end"):
        if c in df:
            df[c] = pd.to_datetime(df[c]).dt.date
    return df


def run(db: Db | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db = db or Db()
    run_id = db.start_run(RUN_LABEL, METHOD_VERSION)
    try:
        fin = _load(db, "fct_lab_financials", "id,ticker,role,metric,period_type,period_end,value,filed_date")
        fil = _load(db, "fct_lab_filings", "id,ticker,role,form,filed_date")
        if fin.empty:
            db.finish_run(run_id, "failed", {}, "fct_lab_financials порожня")
            return 1
        labs = sorted(set(fin.loc[fin["role"] == "lab", "ticker"]) | set(fil.loc[fil["role"] == "lab", "ticker"]))
        rows = build_rows(fin, fil, labs, date.today(), run_id)
        if rows:
            db.upsert("fct_metric_values", rows, on_conflict="metric_id,period_start,region")
        status = "ok" if rows else "failed"
        db.finish_run(run_id, status, {"seen": len(fin), "new": len(rows)}, None if rows else "Немає рядків")
        last = [r for r in rows if r["metric_id"] == "funding_ladder_rung"]
        if last:
            v = int(last[-1]["value"])
            log.info(f"Драбина фінансування на {last[-1]['period_start']}: сходинка {v} ({RUNG_LABELS[v][1]})")
        return 0 if rows else 1
    except Exception as e:
        log.exception("Розрахунок драбини фінансування впав")
        db.finish_run(run_id, "failed", {}, f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
