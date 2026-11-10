"""
core/http.py
Спільні HTTP-хелпери для збирачів.

  get_with_retry() - GET з повторами при тимчасових збоях джерела
                     (429, 5xx, обрив з'єднання, таймаут): 3 спроби з паузою 5 і 15 с.
                     Помилки 4xx, крім 429, не повторюються - це не тимчасове.
  redact()         - прибирає ключі доступу з тексту помилки, перш ніж він потрапить
                     у базу (ops_collector_runs.error, ops_quality_alerts.message).
                     requests пише в помилку повний URL разом з app_key тощо.
"""

from __future__ import annotations

import os
import re
import time
import logging

import requests

log = logging.getLogger("radar.http")

RETRY_STATUS = {429, 500, 502, 503, 504}
DEFAULT_PAUSES = (5, 15)          # секунди між спробами: 1 -> 2 -> 3

# параметри URL, значення яких ніколи не пишемо в базу
_SECRET_PARAMS = re.compile(
    r"((?:app_id|app_key|api_key|apikey|key|token|access_token|secret)=)[^&\s'\"]+", re.IGNORECASE)
# змінні середовища з ключами - їхні значення вирізаються, де б не трапились у тексті
_SECRET_ENV = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "GEMINI_API_KEY", "SUPABASE_KEY")


def redact(text: str | None) -> str | None:
    if not text:
        return text
    text = _SECRET_PARAMS.sub(r"\1***", str(text))
    for name in _SECRET_ENV:
        secret = os.getenv(name, "").strip()
        if len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def get_with_retry(url: str, *, pauses: tuple[float, ...] = DEFAULT_PAUSES,
                   sleep=time.sleep, **kwargs) -> requests.Response:
    """Повертає відповідь з кодом 2xx або кидає останню помилку (вже з вирізаними ключами)."""
    attempts = len(pauses) + 1
    for i in range(attempts):
        try:
            resp = requests.get(url, **kwargs)
            if resp.status_code in RETRY_STATUS and i < attempts - 1:
                log.warning(f"{url}: HTTP {resp.status_code}, спроба {i + 1}/{attempts}; повтор через {pauses[i]} с")
                sleep(pauses[i])
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            if i < attempts - 1:
                log.warning(f"{url}: {type(e).__name__}, спроба {i + 1}/{attempts}; повтор через {pauses[i]} с")
                sleep(pauses[i])
                continue
            raise type(e)(redact(str(e))) from None
        except requests.HTTPError as e:
            raise requests.HTTPError(redact(str(e)), response=e.response) from None
    raise RuntimeError("недосяжно")
