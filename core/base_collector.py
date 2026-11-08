"""
core/base_collector.py
Спільний каркас для всіх збирачів.

Кожен збирач реалізує лише:
    fetch()  -> звідки взяти (список RawItem)
    parse()  -> як розібрати один RawItem у факт (dict) або None, якщо LLM недоступна
і за потреби save() (наприклад, вакансії ще пишуть зв'язки з навичками).

Решту робить каркас:
    * хеш вмісту та запис сирих даних (raw_items, first_seen / last_seen);
    * спільні поля факту: source, last_seen_at, raw_item_id;
    * відкладені записи (LLM недоступна) - повторна обробка в наступних запусках;
    * закриття зниклих фактів (is_active=False), але лише якщо джерело реально відповіло;
    * журнал запусків ops_collector_runs і перевірки якості.
"""

from __future__ import annotations

import sys
import json
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .db import Db, utcnow, iso
from .llm import Llm
from . import quality

log = logging.getLogger("radar.collector")


@dataclass
class RawItem:
    external_id: str
    payload: dict
    content_key: str | None = None   # що саме хешувати; за замовчуванням увесь payload

    @property
    def content_hash(self) -> str:
        text = self.content_key if self.content_key is not None else json.dumps(
            self.payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Deferred(Exception):
    """parse() може кинути це замість повернення None - ефект той самий."""


class Skip(Exception):
    """parse(): сирий запис оброблено, але факту з нього немає (наприклад, у моделі немає T80).
    Не помилка і не відкладення."""


class BaseCollector:
    # --- обов'язкові атрибути підкласу ---
    source: str = ""
    fact_table: str = ""
    # --- необов'язкові ---
    id_column: str = "external_id"     # колонка зовнішнього ідентифікатора у таблиці фактів ("" - немає)
    fact_source: str = ""              # значення колонки source у фактах, якщо відрізняється від source
    on_conflict: str = "external_id,source"
    collection_method: str = "api"     # api / scrape / file / manual_seed
    tracks_presence: bool = False     # чи закривати факти, яких немає в поточному fetch()
    collector_version: str = "1"
    reprocess_limit: int = 20         # скільки відкладених записів добирати за запуск
    allow_empty: bool = False         # чи 0 записів із джерела - це нормально
    run_label: str = ""               # назва в журналі запусків, якщо відрізняється від source

    def __init__(self, db: Db | None = None, llm: Llm | None = None):
        if not self.source or not self.fact_table:
            raise TypeError(f"{type(self).__name__}: задайте source і fact_table")
        self.db = db or Db()
        self.llm = llm or Llm(db=self.db)
        self.log = logging.getLogger(f"radar.{self.source}")

    # ---------- реалізує кожен збирач ----------

    def fetch(self) -> Iterable[RawItem]:
        raise NotImplementedError

    def parse(self, raw: RawItem) -> dict | None:
        raise NotImplementedError

    def save(self, fact: dict, raw: RawItem, raw_id: int) -> None:
        self.db.upsert(self.fact_table, fact, on_conflict=self.on_conflict)

    # ---------- каркас ----------

    def _complete_fact(self, fact: dict, raw: RawItem, raw_id: int, seen_at: datetime) -> dict:
        fact = dict(fact)
        if self.id_column:
            fact.setdefault(self.id_column, raw.external_id)
        fact["source"] = self.fact_source or self.source
        fact.setdefault("collection_method", self.collection_method)
        fact["raw_item_id"] = raw_id
        fact["content_hash"] = raw.content_hash
        fact["last_seen_at"] = iso(seen_at)
        if self.tracks_presence:
            fact["is_active"] = True
        # first_seen_at і verified навмисно НЕ надсилаються:
        # first_seen_at ставить БД при першій вставці, verified змінює лише людина.
        for k in ("first_seen_at", "verified"):
            fact.pop(k, None)
        if not fact.get("extraction_method"):
            raise ValueError("parse() має вказати extraction_method (llm:<модель> / rule / manual)")
        return fact

    def _process(self, raw: RawItem, raw_id: int, seen_at: datetime, stats: dict) -> str:
        """Повертає статус: processed / deferred / failed."""
        try:
            try:
                fact = self.parse(raw)
            except Deferred:
                fact = None
            except Skip:
                self.db.set_raw_status(raw_id, "processed")
                stats["skipped"] += 1
                return "skipped"
            if fact is None:
                self.db.set_raw_status(raw_id, "deferred")
                stats["deferred"] += 1
                return "deferred"
            fact = self._complete_fact(fact, raw, raw_id, seen_at)
            self.save(fact, raw, raw_id)
            self.db.set_raw_status(raw_id, "processed")
            return "processed"
        except Exception as e:
            self.log.exception(f"Помилка обробки {raw.external_id}: {e}")
            try:
                self.db.set_raw_status(raw_id, "failed", f"{type(e).__name__}: {e}")
            except Exception:
                pass
            stats["failed"] += 1
            return "failed"

    def run(self) -> dict:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        self.log.info(f"=== START {self.source} ===")
        started = utcnow()
        stats = {"seen": 0, "new": 0, "updated": 0, "failed": 0, "deferred": 0, "skipped": 0,
                 "reprocessed": 0, "closed": 0, "fetched": 0}
        label = self.run_label or self.source
        run_id = self.db.start_run(label, self.collector_version)
        fetch_error: str | None = None
        touched: set[int] = set()

        # 1. Свіжі дані з джерела
        try:
            items = list(self.fetch())
        except Exception as e:
            self.log.exception(f"fetch() впав: {e}")
            items, fetch_error = [], f"{type(e).__name__}: {e}"
        stats["fetched"] = len(items)

        for raw in items:
            raw_id, is_new = self.db.touch_raw(self.source, raw.external_id, raw.content_hash,
                                               raw.payload, started)
            touched.add(raw_id)
            stats["seen"] += 1
            status = self._process(raw, raw_id, started, stats)
            if status == "processed":
                stats["new" if is_new else "updated"] += 1

        # 2. Добираємо відкладені з попередніх запусків
        if self.reprocess_limit > 0:
            try:
                backlog = self.db.load_raw(self.source, "deferred", self.reprocess_limit + len(touched))
            except Exception as e:
                self.log.warning(f"Не вдалося прочитати відкладені записи: {e}")
                backlog = []
            backlog = [r for r in backlog if r["raw_id"] not in touched][: self.reprocess_limit]
            for row in backlog:
                raw = RawItem(external_id=row["external_id"], payload=row["payload"])
                seen_at = _parse_ts(row.get("last_seen_at")) or started
                if self._process(raw, row["raw_id"], seen_at, stats) == "processed":
                    stats["reprocessed"] += 1

        # 3. Закриваємо зниклі - тільки якщо джерело відповіло і повернуло дані
        if self.tracks_presence and not fetch_error and stats["fetched"] > 0:
            stats["closed"] = self.db.close_stale(self.fact_table, self.fact_source or self.source, started)

        # 4. Журнал і якість
        llm = self.llm.stats
        stats.update(llm_calls=llm.calls, llm_fallbacks=llm.fallbacks, llm_cache_hits=llm.cache_hits)
        if fetch_error:
            status = "failed"
        elif stats["failed"] or stats["deferred"]:
            status = "partial"
        else:
            status = "ok"
        self.db.finish_run(run_id, status, stats, fetch_error)

        alerts = quality.run_checks(self.db, label, run_id, stats, status, fetch_error,
                                    allow_empty=self.allow_empty)
        self.log.info(f"=== FINISH {self.source}: {status} | {stats} ===")
        if any(a["severity"] == "critical" for a in alerts) and quality.fail_on_critical():
            sys.exit(1)   # крок у GitHub Actions стане червоним
        return stats


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
