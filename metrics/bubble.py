"""
metrics/bubble.py
Індекс крихкості інвестиційної бульбашки ШІ, версія v0 -> fct_metric_values (щодня, region='US').

Складники (бал 0-100 кожен, більше = напруженіше):
  bubble_score_credit   fred_baa10y                           вищий спред = кредитори нервують
  bubble_score_hy       fred_hy_oas                           вищий спред = апетит до ризику падає
  bubble_score_rate10y  fred_ust10y                           дорожчі довгі гроші
  bubble_score_policy   fred_fed_funds                        дорожчі короткі гроші
  bubble_score_devjobs  indeed_softdev / indeed_total (US)    розробників шукають менше, ніж ринок загалом
Зведений:
  bubble_fragility      середнє наявних балів (рівні ваги), якщо балів >= MIN_COMPONENTS

Бал = процентиль сьогоднішнього значення серед УСІХ попередніх значень цього ряду
(розширюване вікно, від початку історії до цього дня). Тож для кожного дня в минулому
бал рахується лише з того, що було відомо на той день - без «знання майбутнього».
Це дозволяє чесно подивитися, чи піднімався б індекс перед корекцією 2022 року.

Чесність:
  * бал з'являється лише після MIN_HISTORY днів історії ряду;
  * пропуски (вихідні, запізнення Indeed) заповнюються останнім значенням не довше MAX_FFILL_DAYS;
  * спреди ICE і Moody's на табло показуються лише як бали, не сирими значеннями (ліцензії);
  * v0: ваги й склад - перша версія, не перевірені; змінюйте METHOD_VERSION при будь-якій зміні.

Запуск: python -m metrics.bubble   (після collectors.fred_series)
"""

from __future__ import annotations

import sys
import logging

import pandas as pd

from core.db import Db

log = logging.getLogger("radar.metrics.bubble")

RUN_LABEL = "metrics_bubble"
METHOD_VERSION = "v0"
REGION = "US"
MIN_HISTORY = 250          # ~рік робочих днів
MAX_FFILL_DAYS = 14
MIN_COMPONENTS = 2
REWRITE_DAYS = 60          # після першого повного запису щодня переписуються лише останні 60 днів

# id балу -> (вхідні ряди, напрям: +1 більше = напруженіше, -1 менше = напруженіше)
COMPONENTS = {
    "bubble_score_credit": (("fred_baa10y",), +1),
    "bubble_score_hy": (("fred_hy_oas",), +1),
    "bubble_score_rate10y": (("fred_ust10y",), +1),
    "bubble_score_policy": (("fred_fed_funds",), +1),
    "bubble_score_devjobs": (("indeed_softdev_postings", "indeed_total_postings"), -1),   # відношення
}
INPUTS = sorted({m for ins, _ in COMPONENTS.values() for m in ins})


def expanding_score(s: pd.Series, direction: int, min_history: int = MIN_HISTORY) -> pd.Series:
    """Частка попередніх і поточного значень, що НЕ більші (або не менші) за поточне, x100.
    Чиста функція; s - щоденний ряд без пропусків у межах власної історії."""
    s = s.dropna()
    vals = s.to_numpy()
    out = []
    for i, v in enumerate(vals):
        if i + 1 < min_history:
            out.append(float("nan"))
            continue
        hist = vals[: i + 1]
        share = (hist <= v).mean() if direction > 0 else (hist >= v).mean()
        out.append(round(100.0 * share, 2))
    return pd.Series(out, index=s.index)


def build_scores(raw: dict[str, pd.Series], min_history: int = MIN_HISTORY) -> pd.DataFrame:
    """raw: metric_id -> ряд значень з DatetimeIndex. Повертає DataFrame балів (стовпці = id балів
    і bubble_fragility) на щоденному календарі."""
    if not raw:
        return pd.DataFrame()
    start = min(s.index.min() for s in raw.values() if len(s))
    end = max(s.index.max() for s in raw.values() if len(s))
    cal = pd.date_range(start, end, freq="D")
    daily = {k: s.sort_index().reindex(cal).ffill(limit=MAX_FFILL_DAYS) for k, s in raw.items() if len(s)}

    scores = {}
    for sid, (inputs, direction) in COMPONENTS.items():
        if not all(i in daily for i in inputs):
            continue
        x = daily[inputs[0]] if len(inputs) == 1 else daily[inputs[0]] / daily[inputs[1]]
        first, last = x.first_valid_index(), x.last_valid_index()
        if first is None:
            continue
        x = x.loc[first:last]
        if x.isna().any():           # дірка довша за MAX_FFILL_DAYS - бал лише з безперервного хвоста
            x = x.loc[x[x.isna()].index.max() + pd.Timedelta(days=1):]
        scores[sid] = expanding_score(x, direction, min_history).reindex(cal)

    df = pd.DataFrame(scores, index=cal)
    if df.empty:
        return df
    n = df.notna().sum(axis=1)
    df["bubble_fragility"] = df.mean(axis=1, skipna=True).where(n >= MIN_COMPONENTS).round(2)
    df["_n"] = n
    return df.dropna(how="all", subset=[c for c in df.columns if c != "_n"])


def to_rows(df: pd.DataFrame, run_id) -> list[dict]:
    rows = []
    for d, rec in df.iterrows():
        day = d.date().isoformat()
        for col, v in rec.items():
            if col == "_n" or pd.isna(v):
                continue
            row = {"metric_id": col, "period_start": day, "period_end": day, "region": REGION,
                   "value": float(v), "is_estimate": False, "method_version": METHOD_VERSION, "run_id": run_id}
            if col == "bubble_fragility":
                row["numerator"] = int(rec["_n"])               # скільки складників у середньому
                row["denominator"] = len(COMPONENTS)
            rows.append(row)
    return rows


def load_inputs(db: Db) -> dict[str, pd.Series]:
    raw = {}
    for mid in INPUTS:
        data, offset = [], 0
        while True:     # PostgREST віддає до 1000 рядків за раз
            page = db.table("fct_metric_values").select("period_start,value").eq("metric_id", mid) \
                .eq("region", REGION).order("period_start").range(offset, offset + 999).execute().data or []
            data.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        if data:
            raw[mid] = pd.Series([float(r["value"]) for r in data],
                                 index=pd.to_datetime([r["period_start"] for r in data]))
    return raw


def run(db: Db | None = None, raw: dict[str, pd.Series] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    db = db or Db()
    run_id = db.start_run(RUN_LABEL, METHOD_VERSION)
    try:
        raw = raw if raw is not None else load_inputs(db)
        df = build_scores(raw)
        rows = to_rows(df, run_id)
        prev = db.select("fct_metric_values", "period_start", eq={"metric_id": "bubble_fragility", "region": REGION},
                         order="period_start", desc=True, limit=1)
        if prev:   # історія вже записана: бали минулих днів не змінюються, оновлюємо хвіст
            cutoff = (pd.Timestamp(str(prev[0]["period_start"])[:10]) - pd.Timedelta(days=REWRITE_DAYS)).date().isoformat()
            rows = [r for r in rows if r["period_start"] >= cutoff]
        if rows:
            db.upsert("fct_metric_values", rows, on_conflict="metric_id,period_start,region")
        missing = [m for m in INPUTS if m not in raw]
        status = "ok" if rows and not missing else ("partial" if rows else "failed")
        err = (f"Немає вхідних рядів: {missing}" if missing else None) if rows else "Немає даних для балів"
        db.finish_run(run_id, status, {"seen": len(raw), "new": len(rows)}, err)
        last = df["bubble_fragility"].dropna() if "bubble_fragility" in df else pd.Series(dtype=float)
        log.info(f"Записано {len(rows)} значень; індекс крихкості на "
                 f"{last.index[-1].date() if len(last) else '—'} = {last.iloc[-1] if len(last) else '—'}")
        return 0 if rows else 1
    except Exception as e:
        log.exception("Розрахунок індексу крихкості впав")
        db.finish_run(run_id, "failed", {}, f"{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run())
