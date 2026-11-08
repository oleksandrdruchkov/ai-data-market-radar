"""
core/quality.py
Перевірки після кожного запуску збирача. Результат - записи в ops_quality_alerts
і рівень серйозності: info / warning / critical.

Перевірки, що потребують кількох джерел одразу (наприклад, «наші вакансії
розходяться з Indeed»), та перевірка «джерело давно мовчить» живуть у SQL
(sql/ представлення v_ops_source_freshness), бо їх треба бачити навіть тоді,
коли збирач узагалі не запускався.
"""

from __future__ import annotations

import os
import logging
from statistics import median

log = logging.getLogger("radar.quality")

VOLUME_CHANGE_LIMIT = 0.5      # ±50% від медіани останніх запусків
FAILED_WARN, FAILED_CRIT = 0.2, 0.5
DEFERRED_WARN = 0.5
HISTORY_RUNS = 7


def fail_on_critical() -> bool:
    return os.getenv("RADAR_FAIL_ON_CRITICAL", "1").strip() not in ("0", "false", "no")


def evaluate(stats: dict, status: str, fetch_error: str | None,
             history_seen: list[int], allow_empty: bool = False) -> list[dict]:
    """Чиста функція: лише рахує, нічого не пише. Легко тестувати."""
    alerts: list[dict] = []

    def add(check, severity, message, value=None, threshold=None):
        alerts.append({"check_name": check, "severity": severity, "message": message,
                       "value": value, "threshold": threshold})

    if fetch_error:
        add("fetch_failed", "critical", f"Джерело не відповіло: {fetch_error[:300]}")
        return alerts

    seen = stats.get("seen", 0)
    if seen == 0:
        if not allow_empty:
            add("empty_fetch", "critical", "Джерело повернуло 0 записів", 0, 1)
        return alerts

    failed_share = stats.get("failed", 0) / seen
    if failed_share >= FAILED_CRIT:
        add("failed_share", "critical", f"Помилки обробки: {failed_share:.0%} записів", failed_share, FAILED_CRIT)
    elif failed_share >= FAILED_WARN:
        add("failed_share", "warning", f"Помилки обробки: {failed_share:.0%} записів", failed_share, FAILED_WARN)

    deferred_share = stats.get("deferred", 0) / seen
    if deferred_share >= DEFERRED_WARN:
        add("deferred_share", "warning",
            f"LLM недоступна для {deferred_share:.0%} записів (квоти?) - їх буде дооброблено", deferred_share, DEFERRED_WARN)

    calls = stats.get("llm_calls", 0)
    if calls and stats.get("llm_fallbacks", 0) / calls > 0.5:
        add("llm_fallbacks", "info", "Більшість відповідей дали резервні моделі каскаду",
            stats["llm_fallbacks"] / calls, 0.5)

    hist = [h for h in history_seen if h and h > 0]
    if len(hist) >= 3:
        base = median(hist)
        change = (seen - base) / base
        if abs(change) > VOLUME_CHANGE_LIMIT:
            add("volume_change", "warning",
                f"Кількість записів {seen} проти медіани {base:g} ({change:+.0%})", change, VOLUME_CHANGE_LIMIT)

    return alerts


def run_checks(db, source: str, run_id, stats: dict, status: str, fetch_error: str | None,
               allow_empty: bool = False) -> list[dict]:
    try:
        history = [r for r in db.recent_runs(source, HISTORY_RUNS + 1)
                   if r.get("run_id") != run_id and r.get("status") in ("ok", "partial")]
        history_seen = [r.get("items_seen") or 0 for r in history[:HISTORY_RUNS]]
    except Exception as e:
        log.warning(f"Не вдалося прочитати історію запусків: {e}")
        history_seen = []

    alerts = evaluate(stats, status, fetch_error, history_seen, allow_empty)
    for a in alerts:
        a.update(source=source, run_id=run_id)
        level = {"critical": logging.ERROR, "warning": logging.WARNING}.get(a["severity"], logging.INFO)
        log.log(level, f"[{source}] {a['check_name']}: {a['message']}")
    try:
        db.insert_alerts(alerts)
    except Exception as e:
        log.warning(f"Не вдалося записати попередження: {e}")
    return alerts
