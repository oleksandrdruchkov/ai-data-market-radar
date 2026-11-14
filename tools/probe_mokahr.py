"""
tools/probe_mokahr.py
Діагностика сторінки вакансій DeepSeek / High-Flyer на MokaHR - лише читання, без запису в базу.

БЕЗПЕКА: запити йдуть ЛИШЕ на сторінку, її скрипти й адреси списку вакансій із JOB_ENDPOINTS.
Адреси, знайдені в скриптах, лише друкуються і НЕ викликаються: серед них є дії з акаунтом
кандидата (видалення, зміна імені тощо).

Що робить:
  1) сторінка: вбудовані в HTML налаштування сайту (ключі, згадки про вакансії);
  2) скрипти: рядки зі словами jobs / website / necromancer з контекстом - як застосунок
     будує запит списку і як розшифровує відповідь;
  3) запити до JOB_ENDPOINTS з кількома варіантами параметрів;
  4) якщо відповідь зашифрована ({"data", "necromancer"}) - спроби розшифрувати AES
     ключем necromancer у поширених режимах.

Запуск: python -m tools.probe_mokahr   (потрібен пакет cryptography для кроку 4)
"""

from __future__ import annotations

import os
import re
import json
import html as htmllib
import base64
from urllib.parse import urljoin

import requests

ORG = os.getenv("MOKA_ORG", "high-flyer")
SITE = int(os.getenv("MOKA_SITE", "140576"))
BASE = "https://app.mokahr.com"
PAGE = f"{BASE}/social-recruitment/{ORG}/{SITE}"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 MarketRadarBot/2.0")

# Лише список вакансій. Нічого іншого скрипт не викликає.
JOB_ENDPOINTS = [
    "/api/outer/ats-apply/website/jobs/v2",
    "/api/outer/ats-apply/website/jobs",
    "/api/outer/ats-apply/website/jobs/list",
]
PAYLOADS = [
    {"orgId": ORG, "siteId": SITE, "limit": 10, "offset": 0},
    {"orgId": ORG, "siteId": SITE, "limit": 10, "offset": 0, "site": "social"},
    {"orgId": ORG, "siteId": SITE, "limit": 10, "offset": 0, "needStat": True},
    {"orgId": ORG, "siteId": str(SITE), "pageSize": 10, "page": 1},
]


def cut(text: str, n: int = 300) -> str:
    return text[:n].replace("\n", " ")


def try_decrypt(data_b64: str, key: str) -> str | None:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        return "(немає пакета cryptography)"
    raw = base64.b64decode(data_b64)
    k = key.encode()
    variants = [("ECB", modes.ECB()), ("CBC iv=key", modes.CBC(k[:16])), ("CBC iv=0", modes.CBC(b"\0" * 16))]
    for name, mode in variants:
        try:
            d = Cipher(algorithms.AES(k), mode).decryptor()
            out = d.update(raw) + d.finalize()
            out = out[:-out[-1]] if 0 < out[-1] <= 16 else out
            text = out.decode("utf-8")
            if text.lstrip().startswith(("{", "[")):
                return f"{name}: {cut(text, 800)}"
        except Exception:
            continue
    return None


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", "Referer": PAGE})

    print(f"== 1. Сторінка {PAGE}")
    r = s.get(PAGE, timeout=30)
    page = r.text
    print(f"    HTTP {r.status_code}, {len(page)} символів")
    for blob in re.findall(r"""=\s*["']({&quot;.*?})["']""", page, re.S)[:3]:
        try:
            data = json.loads(htmllib.unescape(blob))
            print(f"    вбудований JSON: ключі {list(data)[:30]}")
            for k, v in data.items():
                if re.search(r"job|position", k, re.I):
                    print(f"      {k}: {cut(json.dumps(v, ensure_ascii=False), 400)}")
        except ValueError:
            print(f"    вбудований блок (не JSON): {cut(htmllib.unescape(blob), 200)}")
    scripts = [urljoin(r.url, src) for src in re.findall(r"""<script[^>]+src=["']([^"']+)""", page)]
    app_js = [u for u in scripts if "recruitmentWeb" in u]

    print("\n== 2. Скрипт застосунку: як будується запит вакансій і розшифровка")
    for src in app_js[:1]:
        js = s.get(src, timeout=60).text
        print(f"    {src.rsplit('/', 1)[-1]}: {len(js)} символів")
        for word in ("website/jobs", "ats-apply/website", "necromancer", "AES", "decrypt"):
            hits = [m.start() for m in re.finditer(re.escape(word), js)][:4]
            print(f"    «{word}»: {len(re.findall(re.escape(word), js))} згадок")
            for h in hits:
                print(f"      ...{cut(js[max(0, h - 200): h + 250], 450)}...")

    print("\n== 3. Запити списку вакансій (лише читання)")
    for path in JOB_ENDPOINTS:
        for payload in PAYLOADS:
            try:
                resp = s.post(BASE + path, json=payload, timeout=30)
            except Exception as e:
                print(f"  {path} {payload} -> {type(e).__name__}")
                continue
            body = resp.text
            print(f"  {path} {json.dumps(payload, ensure_ascii=False)} -> HTTP {resp.status_code}: {cut(body, 250)}")
            try:
                data = resp.json()
            except ValueError:
                continue
            if isinstance(data, dict) and "necromancer" in data and isinstance(data.get("data"), str):
                print(f"    зашифровано; розшифровка: {try_decrypt(data['data'], data['necromancer'])}")
                break                       # для цієї адреси досить


if __name__ == "__main__":
    main()
