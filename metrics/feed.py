"""
metrics/feed.py
Плитка «Стан збору даних» на сторінці: зведення v_ops_source_freshness (sql/001) в один стан.

Чиста функція, без бази й без Streamlit. Свіжість кожного джерела рахує база:
  fresh     останній успішний запуск не старший за два очікувані інтервали джерела
  failing   останній запуск упав, але успішний ще не застарів
  stale     успішного запуску немає довше за два інтервали
  never_ok  джерело ще жодного разу не відпрацювало успішно
  disabled  джерело вимкнено
"""

from __future__ import annotations

import math


def feed_status(rows: list[dict]) -> dict:
    """rows: рядки v_ops_source_freshness.

    Повертає:
      level      "ok" - усі ввімкнені джерела свіжі; "warn" - є проблемні; "bad" - проблемних
                 половина чи більше або свіжих немає; "unknown" - рядків немає
      fresh      скільки джерел свіжі
      total      скільки ввімкнених джерел, що вже мали хоч один успішний запуск або зараз падають
      problems   [(джерело, стан, годин від останнього успіху або None)] - failing і stale
      never      джерела, що ще не запускались успішно (не рахуються ні у свіжі, ні у проблемні,
                 якщо останній запуск не впав: напр., щомісячний збирач до першого запуску)
      hours      годин від найсвіжішого успішного запуску будь-якого джерела (None, якщо не було)"""
    enabled = [r for r in rows or [] if r.get("is_enabled", True) and r.get("freshness") != "disabled"]
    if not enabled:
        return {"level": "unknown", "fresh": 0, "total": 0, "problems": [], "never": [], "hours": None}

    def hours(r):
        h = r.get("hours_since_ok")
        try:
            h = float(h)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(h) else h

    fresh = [r for r in enabled if r.get("freshness") == "fresh"]
    problems = [(r["source"], r["freshness"], hours(r)) for r in enabled if r.get("freshness") in ("failing", "stale")]
    never = []
    for r in enabled:
        if r.get("freshness") == "never_ok":
            if r.get("last_status") == "failed":          # запускалось і впало - це проблема, а не «ще не час»
                problems.append((r["source"], "failing", None))
            else:
                never.append(r["source"])
    total = len(fresh) + len(problems)
    known = [h for h in (hours(r) for r in enabled) if h is not None]
    if not problems and fresh:
        level = "ok"
    elif not fresh or len(problems) * 2 >= total:
        level = "bad"
    else:
        level = "warn"
    problems.sort(key=lambda p: (p[1] != "stale", p[0]))
    return {"level": level, "fresh": len(fresh), "total": total, "problems": problems,
            "never": sorted(never), "hours": min(known) if known else None}
