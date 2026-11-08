"""
core/llm.py
Один каскад Gemini для всіх збирачів.

Що робить:
  * перебирає моделі каскаду; модель, що вичерпала квоту або не існує (429/404),
    вимикається до кінця запуску, щоб не палити запити;
  * перевіряє відповідь pydantic-схемою: рівні, треки, категорії лише з допустимого списку;
    невалідна відповідь = спроба наступної моделі;
  * кешує успішну відповідь у ops_llm_cache за (prompt_name, prompt_version, content_hash):
    той самий текст з тим самим промптом не тратить квоту двічі;
  * якщо жодна модель не дала валідної відповіді, повертає None.
    Нічого не вигадує: збирач позначить запис як «відкладений» і обробить наступного разу.
"""

from __future__ import annotations

import os
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger("radar.llm")

T = TypeVar("T", bound=BaseModel)

DEFAULT_CASCADE = [
    "gemini-3.5-flash-lite",  # найвищі безкоштовні квоти, базова модель
    "gemini-3.6-flash",       # стабільний резерв
    "gemini-3.8-flash",       # флагман Flash, малий денний ліміт
]

# Ознаки помилок, після яких модель вимикається до кінця запуску
DEAD_MARKERS = ("RESOURCE_EXHAUSTED", "429", "404", "NOT_FOUND", "PERMISSION_DENIED")
# Тимчасові помилки: пробуємо наступну модель, але цю не вимикаємо
TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "500", "INTERNAL", "DEADLINE", "timeout", "Timeout")


def _cascade_from_env() -> list[str]:
    raw = os.getenv("GEMINI_MODELS", "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()] or list(DEFAULT_CASCADE)


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    return t.strip()


@dataclass
class LlmResult(Generic[T]):
    data: T
    model: str            # яка модель відповіла (або з якої моделі кеш)
    cached: bool
    fallback: bool        # відповіла не перша модель каскаду

    @property
    def method(self) -> str:
        return f"llm:{self.model}"


@dataclass
class LlmStats:
    calls: int = 0
    fallbacks: int = 0
    cache_hits: int = 0
    failures: int = 0
    by_model: dict = field(default_factory=dict)


class Llm:
    def __init__(self, db=None, client: Any | None = None, models: list[str] | None = None,
                 min_interval_sec: float | None = None, use_cache: bool = True,
                 sleep=time.sleep):
        self.db = db
        self.models = models or _cascade_from_env()
        self.min_interval = (float(os.getenv("LLM_MIN_INTERVAL_SEC", "6"))
                             if min_interval_sec is None else min_interval_sec)
        self.use_cache = use_cache and db is not None
        self.stats = LlmStats()
        self._client = client
        self._dead: set[str] = set()
        self._last_call = 0.0
        self._sleep = sleep

    # ---------- клієнт ----------

    @property
    def available(self) -> bool:
        return self._get_client() is not None and len(self._dead) < len(self.models)

    def _get_client(self):
        if self._client is None:
            key = os.getenv("GEMINI_API_KEY", "").strip()
            if not key:
                return None
            from google import genai
            self._client = genai.Client(api_key=key)
        return self._client

    def _call(self, model: str, prompt: str, temperature: float) -> str:
        from google.genai import types
        resp = self._get_client().models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        return resp.text or ""

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0 and self._last_call > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    # ---------- кеш ----------

    def _cache_get(self, prompt_name: str, prompt_version: str, content_hash: str):
        if not self.use_cache:
            return None
        try:
            rows = self.db.select("ops_llm_cache", "model,response",
                                  eq={"prompt_name": prompt_name,
                                      "prompt_version": prompt_version,
                                      "content_hash": content_hash},
                                  limit=1)
            return rows[0] if rows else None
        except Exception as e:  # кеш не має ламати збір
            log.warning(f"Кеш LLM недоступний: {e}")
            return None

    def _cache_put(self, prompt_name: str, prompt_version: str, content_hash: str,
                   model: str, response: dict) -> None:
        if not self.use_cache:
            return
        try:
            self.db.upsert("ops_llm_cache", {
                "prompt_name": prompt_name,
                "prompt_version": prompt_version,
                "content_hash": content_hash,
                "model": model,
                "response": response,
            }, on_conflict="prompt_name,prompt_version,content_hash")
        except Exception as e:
            log.warning(f"Не вдалося записати кеш LLM: {e}")

    # ---------- головний метод ----------

    def extract(self, *, prompt: str, schema: type[T], prompt_name: str,
                prompt_version: str, content_hash: str,
                temperature: float = 0.2, models: list[str] | None = None) -> LlmResult[T] | None:
        """models - власний порядок моделей (напр. для незалежної другої думки); інакше каскад."""
        cascade = models or self.models
        if models:   # друга думка кешується окремо від першої
            prompt_name = f"{prompt_name}@{'+'.join(models)}"
        cached = self._cache_get(prompt_name, prompt_version, content_hash)
        if cached:
            try:
                data = schema.model_validate(cached["response"])
                self.stats.cache_hits += 1
                return LlmResult(data=data, model=cached["model"], cached=True, fallback=False)
            except ValidationError:
                log.warning("Запис кешу не відповідає поточній схемі, запитую модель заново.")

        if self._get_client() is None:
            log.warning("GEMINI_API_KEY не задано: запис буде відкладено.")
            self.stats.failures += 1
            return None

        for idx, model in enumerate(cascade):
            if model in self._dead:
                continue
            self._throttle()
            self.stats.calls += 1
            try:
                text = self._call(model, prompt, temperature)
            except Exception as e:
                err = str(e)
                if any(m in err for m in DEAD_MARKERS):
                    self._dead.add(model)
                    log.warning(f"{model}: квота/недоступна ({err[:90]}). Вимкнено до кінця запуску.")
                elif any(m in err for m in TRANSIENT_MARKERS):
                    log.warning(f"{model}: тимчасова помилка ({err[:90]}). Пробую наступну.")
                else:
                    log.error(f"{model}: непередбачена помилка ({err[:200]}). Пробую наступну.")
                continue

            try:
                raw = json.loads(_strip_fences(text))
                data = schema.model_validate(raw)
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning(f"{model}: відповідь не пройшла перевірку схеми ({str(e)[:200]}).")
                continue

            fallback = idx > 0
            self.stats.fallbacks += int(fallback)
            self.stats.by_model[model] = self.stats.by_model.get(model, 0) + 1
            self._cache_put(prompt_name, prompt_version, content_hash, model,
                            data.model_dump(mode="json"))
            return LlmResult(data=data, model=model, cached=False, fallback=fallback)

        self.stats.failures += 1
        log.warning("Жодна модель каскаду не дала валідної відповіді: запис відкладено.")
        return None
