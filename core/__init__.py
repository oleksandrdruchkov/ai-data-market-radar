try:  # локальний запуск: змінні з .env; у GitHub Actions - із Secrets
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .base_collector import BaseCollector, RawItem, Deferred, Skip
from .db import Db
from .llm import Llm, LlmResult

__all__ = ["BaseCollector", "RawItem", "Deferred", "Skip", "Db", "Llm", "LlmResult"]
