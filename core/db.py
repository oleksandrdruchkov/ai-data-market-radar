"""
core/db.py
Єдиний клієнт Supabase для всіх збирачів і невеликі хелпери запису.

Збирачі не звертаються до supabase-py напряму: усе йде через клас Db.
Так у тестах його легко підмінити (tests/fakes.py), а логіка «як писати»
(перші/останні появи, журнал запусків, закриття зниклих) живе в одному місці.
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger("radar.db")

BATCH = 100


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Db:
    """Тонка обгортка над supabase-py. Клієнт створюється ліниво при першому зверненні."""

    def __init__(self, client: Any | None = None):
        self._client = client

    # ---------- підключення ----------

    @property
    def client(self):
        if self._client is None:
            from supabase import create_client  # імпорт тут, щоб тести не потребували пакета

            url = os.getenv("SUPABASE_URL", "").strip()
            key = os.getenv("SUPABASE_KEY", "").strip()
            if not url or not key:
                raise RuntimeError("Відсутні SUPABASE_URL або SUPABASE_KEY (GitHub Secrets / .env).")
            self._client = create_client(url, key)
        return self._client

    def table(self, name: str):
        return self.client.table(name)

    # ---------- загальні операції ----------

    def select(self, table: str, columns: str = "*", *, eq: dict | None = None,
               ilike: dict | None = None, in_: dict | None = None,
               order: str | None = None, desc: bool = False, limit: int | None = None) -> list[dict]:
        q = self.table(table).select(columns)
        for k, v in (eq or {}).items():
            q = q.eq(k, v)
        for k, v in (ilike or {}).items():
            q = q.ilike(k, v)
        for k, v in (in_ or {}).items():
            q = q.in_(k, list(v))
        if order:
            q = q.order(order, desc=desc)
        if limit:
            q = q.limit(limit)
        return q.execute().data or []

    def upsert(self, table: str, rows: dict | list[dict], on_conflict: str,
               ignore_duplicates: bool = False) -> list[dict]:
        rows = [rows] if isinstance(rows, dict) else list(rows)
        out: list[dict] = []
        for i in range(0, len(rows), BATCH):
            res = (self.table(table)
                   .upsert(rows[i:i + BATCH], on_conflict=on_conflict,
                           ignore_duplicates=ignore_duplicates)
                   .execute())
            out.extend(res.data or [])
        return out

    def insert(self, table: str, rows: dict | list[dict]) -> list[dict]:
        return self.table(table).insert(rows).execute().data or []

    def update(self, table: str, values: dict, *, eq: dict) -> list[dict]:
        q = self.table(table).update(values)
        for k, v in eq.items():
            q = q.eq(k, v)
        return q.execute().data or []

    def delete(self, table: str, *, eq: dict, is_null: tuple = ()) -> None:
        q = self.table(table).delete()
        for k, v in eq.items():
            q = q.eq(k, v)
        for k in is_null:
            q = q.is_(k, "null")
        q.execute()

    def delete_not_in(self, table: str, *, eq: dict, column: str, keep: list) -> None:
        """Видаляє рядки за eq, крім тих, де column у keep (оновлення зв'язків «багато-до-багатьох»)."""
        q = self.table(table).delete()
        for k, v in eq.items():
            q = q.eq(k, v)
        if keep:
            q = q.not_.in_(column, list(keep))
        q.execute()

    def rpc(self, fn: str, params: dict) -> Any:
        return self.client.rpc(fn, params).execute().data

    # ---------- журнал запусків ----------

    def start_run(self, source: str, collector_version: str) -> int | None:
        rows = self.insert("ops_collector_runs", {
            "source": source,
            "collector_version": collector_version,
            "status": "running",
            "started_at": iso(utcnow()),
        })
        return rows[0]["run_id"] if rows else None

    def finish_run(self, run_id: int | None, status: str, stats: dict, error: str | None = None) -> None:
        if run_id is None:
            return
        self.update("ops_collector_runs", {
            "status": status,
            "finished_at": iso(utcnow()),
            "items_seen": stats.get("seen", 0),
            "items_new": stats.get("new", 0),
            "items_updated": stats.get("updated", 0),
            "items_failed": stats.get("failed", 0),
            "items_deferred": stats.get("deferred", 0),
            "items_closed": stats.get("closed", 0),
            "llm_calls": stats.get("llm_calls", 0),
            "llm_fallbacks": stats.get("llm_fallbacks", 0),
            "llm_cache_hits": stats.get("llm_cache_hits", 0),
            "error": (error or "")[:2000] or None,
        }, eq={"run_id": run_id})

    def recent_runs(self, source: str, limit: int = 10) -> list[dict]:
        return self.select("ops_collector_runs", eq={"source": source},
                           order="started_at", desc=True, limit=limit)

    # ---------- сирі дані ----------

    def touch_raw(self, source: str, external_id: str, content_hash: str,
                  payload: dict, seen_at: datetime) -> tuple[int, bool]:
        """Записує сирий об'єкт або оновлює last_seen_at, якщо такий хеш уже був.
        Повертає (raw_id, is_new). first_seen_at ніколи не перезаписується (SQL-функція)."""
        data = self.rpc("radar_touch_raw", {
            "p_source": source,
            "p_external_id": external_id,
            "p_content_hash": content_hash,
            "p_payload": payload,
            "p_seen_at": iso(seen_at),
        })
        row = data[0] if isinstance(data, list) else data
        return int(row["raw_id"]), bool(row["is_new"])

    def set_raw_status(self, raw_id: int, status: str, error: str | None = None) -> None:
        values = {"status": status, "error": (error or "")[:2000] or None}
        if status == "processed":
            values["processed_at"] = iso(utcnow())
        self.update("raw_items", values, eq={"raw_id": raw_id})

    def load_raw(self, source: str, status: str, limit: int) -> list[dict]:
        return self.select("raw_items", "raw_id,external_id,content_hash,payload,last_seen_at",
                           eq={"source": source, "status": status},
                           order="first_seen_at", limit=limit)

    # ---------- факти ----------

    def close_stale(self, table: str, source: str, seen_before: datetime) -> int:
        """is_active=False для фактів джерела, яких не було в поточному запуску."""
        res = (self.table(table)
               .update({"is_active": False, "closed_at": iso(utcnow())})
               .eq("source", source)
               .eq("is_active", True)
               .lt("last_seen_at", iso(seen_before))
               .execute())
        return len(res.data or [])

    # ---------- якість ----------

    def insert_alerts(self, alerts: Iterable[dict]) -> None:
        alerts = list(alerts)
        if alerts:
            self.insert("ops_quality_alerts", alerts)
