"""
tools/probe_mokahr.py
Діагностика сторінки вакансій DeepSeek / High-Flyer на MokaHR - лише друк, без запису в базу.

Сторінка https://app.mokahr.com/social-recruitment/high-flyer/140576 - веб-застосунок, що
підтягує вакансії внутрішнім запитом. Скрипт шукає цей запит:
  1) завантажує сторінку: статус, заголовок, скрипти, згадки orgId/siteId/api;
  2) завантажує скрипти застосунку й виписує шляхи /api/..., пов'язані з вакансіями;
  3) пробує ймовірні адреси (відомі + знайдені в скриптах) і друкує початок відповіді.
За результатом пишеться справжній збирач collectors/jobs_deepseek.py.

Змінні: MOKA_ORG="high-flyer"  MOKA_SITE="140576"
Запуск: python -m tools.probe_mokahr
"""

from __future__ import annotations

import os
import re
import json
from urllib.parse import urljoin

import requests

ORG = os.getenv("MOKA_ORG", "high-flyer")
SITE = os.getenv("MOKA_SITE", "140576")
BASE = "https://app.mokahr.com"
PAGE = f"{BASE}/social-recruitment/{ORG}/{SITE}"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 MarketRadarBot/2.0")
HDR = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Referer": PAGE}

API_RE = re.compile(r"""["'`](/api/[A-Za-z0-9_\-/{}.$]+)["'`]""")
JOBISH = re.compile(r"job|position|apply|website|recruit|social", re.I)


def show(label: str, text: str, n: int = 400) -> None:
    print(f"    {label}: {text[:n].replace(chr(10), ' ')}")


def main() -> None:
    s = requests.Session()
    s.headers.update(HDR)

    print(f"== 1. Сторінка {PAGE}")
    r = s.get(PAGE, timeout=30)
    html = r.text
    print(f"    HTTP {r.status_code}, {len(html)} символів, кінцева адреса {r.url}")
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    print(f"    title: {m.group(1).strip() if m else '-'}")
    scripts = [urljoin(r.url, src) for src in re.findall(r"""<script[^>]+src=["']([^"']+)""", html)]
    print(f"    скриптів: {len(scripts)}")
    for src in scripts[:15]:
        print(f"      {src}")
    for key in ("orgId", "siteId", "orgName", "jobs", "__INITIAL_STATE__", "window.__"):
        for hit in re.finditer(re.escape(key), html):
            show(f"згадка {key}", html[max(0, hit.start() - 80): hit.start() + 160], 240)
            break

    print("\n== 2. Шляхи /api/ у скриптах застосунку")
    found: list[str] = []
    for src in scripts[:12]:
        try:
            js = s.get(src, timeout=30).text
        except Exception as e:
            print(f"    {src}: {type(e).__name__}")
            continue
        paths = sorted({p for p in API_RE.findall(js) if JOBISH.search(p)})
        if paths:
            print(f"    {src.rsplit('/', 1)[-1]}: {len(paths)}")
            for p in paths[:40]:
                print(f"      {p}")
            found += [p for p in paths if p not in found]

    print("\n== 3. Спроби запитів")
    payload = {"orgId": ORG, "siteId": int(SITE), "limit": 10, "offset": 0}
    tries = [
        ("POST", "/api/outer/ats-apply/website/jobs/v2"),
        ("POST", "/api/outer/ats-apply/website/jobs"),
        ("GET", "/api/outer/ats-apply/website/jobs"),
    ] + [("POST", p) for p in found if "{" not in p and "$" not in p][:15]
    seen = set()
    for method, path in tries:
        if (method, path) in seen:
            continue
        seen.add((method, path))
        url = BASE + path
        try:
            if method == "POST":
                resp = s.post(url, json=payload, timeout=30)
            else:
                resp = s.get(url, params=payload, timeout=30)
            body = resp.text
            kind = "json" if body.lstrip().startswith(("{", "[")) else "text"
            print(f"  {method} {path} -> HTTP {resp.status_code} ({kind}, {len(body)} симв.)")
            if kind == "json":
                try:
                    data = json.loads(body)
                    show("ключі", json.dumps(list(data)[:15] if isinstance(data, dict) else type(data).__name__,
                                             ensure_ascii=False))
                except ValueError:
                    pass
            show("початок", body, 500)
        except Exception as e:
            print(f"  {method} {path} -> {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
