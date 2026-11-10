"""
Тестова заміна core.db.Db, що працює з локальним Postgres через psql
і повторює семантику PostgREST (upsert оновлює лише передані колонки).
Мета - перевірити, що Python-код і SQL-міграція узгоджені за назвами колонок і типами.
"""

from __future__ import annotations

import json
import os
import subprocess

from core.db import Db, iso


def _lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


class PgDb(Db):
    def __init__(self, dsn_args: list[str]):
        super().__init__(client=object())
        self.args = dsn_args

    def sql(self, query: str):
        out = subprocess.run(["psql", *self.args, "-v", "ON_ERROR_STOP=1", "-qtA", "-c", query],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip())
        txt = out.stdout.strip()
        return json.loads(txt) if txt else None

    def _rows(self, query: str) -> list[dict]:
        return self.sql(f"SELECT COALESCE(json_agg(t), '[]') FROM ({query}) t") or []

    def _dml(self, stmt: str) -> list[dict]:
        """stmt - INSERT/UPDATE ... RETURNING *"""
        return self.sql(f"WITH x AS ({stmt}) SELECT COALESCE(json_agg(x), '[]') FROM x") or []

    # --- примітиви ---
    def select(self, table, columns="*", *, eq=None, ilike=None, in_=None, order=None, desc=False, limit=None):
        where = [f"{k} = {_lit(v)}" for k, v in (eq or {}).items()]
        where += [f"{k} ILIKE {_lit(v)}" for k, v in (ilike or {}).items()]
        where += [f"{k} IN ({','.join(_lit(x) for x in v)})" for k, v in (in_ or {}).items()]
        q = f"SELECT {columns} FROM {table}"
        if where:
            q += " WHERE " + " AND ".join(where)
        if order:
            q += f" ORDER BY {order} {'DESC' if desc else 'ASC'}"
        if limit:
            q += f" LIMIT {limit}"
        return self._rows(q)

    def upsert(self, table, rows, on_conflict, ignore_duplicates=False):
        rows = [rows] if isinstance(rows, dict) else list(rows)
        if not rows:
            return []
        cols = list(rows[0].keys())
        payload = json.dumps(rows, default=str)
        collist = ", ".join(cols)
        conflict_cols = [c.strip() for c in on_conflict.split(",")]
        upd = [c for c in cols if c not in conflict_cols]
        action = ("DO NOTHING" if ignore_duplicates or not upd else
                  "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in upd))
        q = (f"INSERT INTO {table} ({collist}) "
             f"SELECT {collist} FROM jsonb_populate_recordset(NULL::{table}, {_lit(payload)}::jsonb) "
             f"ON CONFLICT ({on_conflict}) {action} RETURNING *")
        return self._dml(q)

    def insert(self, table, rows):
        rows = [rows] if isinstance(rows, dict) else list(rows)
        cols = ", ".join(rows[0].keys())
        payload = json.dumps(rows, default=str)
        return self._dml(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM "
                          f"jsonb_populate_recordset(NULL::{table}, {_lit(payload)}::jsonb) RETURNING *")

    def update(self, table, values, *, eq):
        def val(v):
            if v is None:
                return "NULL"
            return _lit(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
        sets = ", ".join(f"{k} = {val(v)}" for k, v in values.items())
        where = " AND ".join(f"{k} = {_lit(v)}" for k, v in eq.items())
        return self._dml(f"UPDATE {table} SET {sets} WHERE {where} RETURNING *")

    def delete(self, table, *, eq, is_null=()):
        where = [f"{k} = {_lit(v)}" for k, v in eq.items()] + [f"{k} IS NULL" for k in is_null]
        self.sql(f"DELETE FROM {table} WHERE " + " AND ".join(where))

    def delete_not_in(self, table, *, eq, column, keep):
        where = " AND ".join(f"{k} = {_lit(v)}" for k, v in eq.items())
        if keep:
            where += f" AND {column} NOT IN ({','.join(_lit(x) for x in keep)})"
        self.sql(f"DELETE FROM {table} WHERE {where}")

    def rpc(self, fn, params):
        args = ", ".join(f"{k} => {_lit(json.dumps(v) if isinstance(v, (dict, list)) else v)}"
                         for k, v in params.items())
        return self._rows(f"SELECT * FROM {fn}({args})")

    def close_stale(self, table, source, seen_before):
        rows = self._dml(f"UPDATE {table} SET is_active = false, closed_at = now() "
                          f"WHERE source = {_lit(source)} AND is_active "
                          f"AND last_seen_at < {_lit(iso(seen_before))} RETURNING 1 AS one")
        return len(rows)


def pg_args() -> list[str] | None:
    raw = os.getenv("RADAR_TEST_PG")   # напр. "-h /tmp -p 5499 -U postgres"
    return raw.split() if raw else None
