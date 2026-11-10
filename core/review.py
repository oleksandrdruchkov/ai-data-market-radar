"""
core/review.py
Рішення людини щодо записів кола лідерів (fct_leader_action_rates).
Використовує сторінка pages/review.py; тут лише логіка - її легко тестувати.

Стани запису:
  чекає на людину:  verified = false, verified_by IS NULL
  підтверджено:     verified = true,  verified_by = 'human'   (або 'auto' - автоперевірка кодом)
  відхилено:        verified = false, verified_by = 'human',  причина в notes

На коло та в чергу потрапляє лише реальне використання (REAL_METHOD);
див. sql/013_real_use_only_and_review.sql.
"""

from __future__ import annotations

import hmac

from core.db import Db, iso, utcnow

TABLE = "fct_leader_action_rates"
REAL_METHOD = "internal_use_sample"
FIELDS = ("id,lab,model_name,release_date,source_doc,source_url,section,page,method,unit,classifier,"
          "n_total,n_out,rate_out,counted,excluded,evidence_quote,data_origin,verified,verified_by,"
          "verified_at,notes,verification_log")


def check_password(entered: str | None, expected: str | None) -> bool:
    """Порожній пароль у налаштуваннях = вхід вимкнено (а не «пускати всіх»)."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def pending(db: Db) -> list[dict]:
    rows = db.select(TABLE, FIELDS, eq={"verified": False, "method": REAL_METHOD},
                     order="release_date", desc=True)
    return [r for r in rows if r.get("verified_by") is None]


def decided(db: Db, limit: int = 20) -> list[dict]:
    return db.select(TABLE, FIELDS, eq={"verified_by": "human"}, order="verified_at", desc=True, limit=limit)


def _get(db: Db, rec_id: int) -> dict:
    rows = db.select(TABLE, FIELDS, eq={"id": rec_id}, limit=1)
    if not rows:
        raise ValueError(f"Запис {rec_id} не знайдено")
    return rows[0]


def _log(row: dict, text: str) -> list:
    log = row.get("verification_log") or []
    return [*log, text] if isinstance(log, list) else [str(log), text]


def approve(db: Db, rec_id: int, comment: str = "") -> dict:
    row = _get(db, rec_id)
    if row.get("method") != REAL_METHOD:
        raise ValueError("Підтвердити можна лише дані реального використання, не тест чи симуляцію")
    note = "Підтверджено людиною" + (f": {comment.strip()}" if comment.strip() else "")
    out = db.update(TABLE, {"verified": True, "verified_by": "human", "verified_at": iso(utcnow()),
                            "notes": note, "verification_log": _log(row, note)}, eq={"id": rec_id})
    return out[0] if out else {}


def reject(db: Db, rec_id: int, reason: str) -> dict:
    if not reason or not reason.strip():
        raise ValueError("Вкажіть причину відхилення")
    row = _get(db, rec_id)
    note = f"Відхилено людиною: {reason.strip()}"
    out = db.update(TABLE, {"verified": False, "verified_by": "human", "verified_at": iso(utcnow()),
                            "notes": note, "verification_log": _log(row, note)}, eq={"id": rec_id})
    return out[0] if out else {}


def undo(db: Db, rec_id: int) -> dict:
    """Скасувати рішення людини: запис знову чекає на перевірку."""
    row = _get(db, rec_id)
    if row.get("verified_by") != "human":
        raise ValueError("Скасувати можна лише рішення людини")
    note = "Рішення людини скасовано"
    out = db.update(TABLE, {"verified": False, "verified_by": None, "verified_at": None,
                            "notes": note, "verification_log": _log(row, note)}, eq={"id": rec_id})
    return out[0] if out else {}
