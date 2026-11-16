"""
tools/probe_cn_careers.py
Діагностика сторінок найму китайських лабораторій-лідерів (лідери за ECI) - лише читання,
без запису в базу і без жодних дій з акаунтами кандидатів.

Що вже відомо (запуск 2026-11-16):
  Moonshot (Kimi)  MokaHR: app.mokahr.com/social-recruitment/moonshot/148506 (як DeepSeek)
  MiniMax          Feishu: vrfi1sk8a0.jobs.feishu.cn/379481
  Zhipu (Z.ai)     невідомо - шукаємо тут
  Alibaba          загальний портал усієї корпорації (talent.alibaba.com), не лабораторії

Цей запуск:
  1) Feishu (MiniMax): чи віддає сторінка або публічний запит списку загальну кількість вакансій.
     Викликаються ЛИШЕ: сторінка, видача токена захисту форми і пошук вакансій (читання).
  2) Zhipu: слова «招聘 / 加入 / join / career» у HTML сайту з контекстом.
  3) MokaHR (Moonshot): лічильник jobStats і розбивка за категоріями.

Запуск: python -m tools.probe_cn_careers
"""

from __future__ import annotations

import re
import sys
import json
import html as htmllib

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 MarketRadarBot/2.0")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
TIMEOUT = 40


def show(label: str, text: str, n: int = 600) -> None:
    print(f"    {label}: {text[:n]!r}")


def feishu(host: str, path: str) -> None:
    print(f"\n===== Feishu: {host}/{path} =====")
    s = requests.Session()
    s.headers.update(HEADERS)
    base = f"https://{host}"
    for url in (f"{base}/{path}", f"{base}/index"):
        try:
            r = s.get(url, timeout=TIMEOUT)
        except Exception as ex:
            print(f"  GET {url}: {type(ex).__name__}: {str(ex)[:120]}")
            continue
        body = r.text or ""
        print(f"  GET {url}: {r.status_code}, {len(body)} символів, cookies: {sorted(s.cookies.keys())}")
        for key in ("job_post_list", "jobPostList", "count", "total", "__INITIAL_STATE__", "__NEXT_DATA__",
                    "portal_type", "website_id", "websiteId", "csrf", "_signature", "job_post_count"):
            for m in list(re.finditer(re.escape(key), body))[:2]:
                show(f"«{key}»", body[max(0, m.start() - 80): m.start() + 220], 300)
        for src in re.findall(r"""<script[^>]+src=["']([^"']+)["']""", body)[:20]:
            print(f"    script: {src[:160]}")
    # токен захисту форми (його просить сам сайт перед будь-яким запитом)
    token = None
    try:
        r = s.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1}, timeout=TIMEOUT,
                   headers={"website-path": path, "Referer": f"{base}/{path}", "Origin": base})
        print(f"  POST csrf/token: {r.status_code}")
        show("тіло", r.text, 300)
        token = s.cookies.get("atsx-csrf-token") or (r.json().get("data") or {}).get("token")
        print(f"    cookies: {sorted(s.cookies.keys())}; token: {'є' if token else 'немає'}")
    except Exception as ex:
        print(f"  csrf/token: {type(ex).__name__}: {str(ex)[:160]}")
    from urllib.parse import unquote
    hdr = {"website-path": path, "Referer": f"{base}/{path}", "Origin": base, "portal-channel": "office",
           "portal-platform": "pc", "Content-Type": "application/json"}
    if token:
        hdr["x-csrf-token"] = unquote(token)
    body = {"keyword": "", "limit": 10, "offset": 0, "job_category_id_list": [], "tag_id_list": [],
            "location_code_list": [], "subject_id_list": [], "recruitment_id_list": [],
            "portal_type": 6, "job_function_id_list": [], "storefront_id_list": [], "portal_entrance": 1}
    for q in ("?keyword=&limit=10&offset=0&portal_type=6&portal_entrance=1",
              "?keyword=&limit=10&offset=0&portal_type=2&portal_entrance=1", ""):
        try:
            r = s.post(f"{base}/api/v1/search/job/posts{q}", json={**body, "portal_type": 2 if "type=2" in q else 6},
                       headers=hdr, timeout=TIMEOUT)
            print(f"  POST search/job/posts{q}: {r.status_code}")
            try:
                j = r.json()
                data = j.get("data") or {}
                print(f"    code={j.get('code')} message={j.get('message')!r} ключі data: {sorted(data)[:12]}")
                print(f"    count={data.get('count')} у списку={len(data.get('job_post_list') or [])}")
                for job in (data.get("job_post_list") or [])[:3]:
                    print("    вакансія:", json.dumps({k: job.get(k) for k in
                          ("id", "title", "publish_time", "job_category", "recruit_type", "city_info")},
                          ensure_ascii=False)[:400])
            except ValueError:
                show("не JSON", r.text, 300)
        except Exception as ex:
            print(f"  search{q}: {type(ex).__name__}: {str(ex)[:160]}")


def zhipu() -> None:
    print("\n===== Zhipu: слова про найм у HTML =====")
    for url in ("https://www.zhipuai.cn/zh", "https://www.zhipuai.cn/en", "https://www.zhipuai.cn/zh/joinus",
                "https://www.zhipuai.cn/zh/join-us", "https://www.zhipuai.cn/zh/careers",
                "https://www.zhipuai.cn/zh/company/join", "https://zhipu.jobs.feishu.cn/index",
                "https://zhipuai.zhiye.com/", "https://app.mokahr.com/apply/zhipuhuazhang",
                "https://app.mokahr.com/apply/bigmodel", "https://app.mokahr.com/apply/zai"):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as ex:
            print(f"  GET {url}: {type(ex).__name__}: {str(ex)[:120]}")
            continue
        body = r.text or ""
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S)
        print(f"  GET {url}: {r.status_code} -> {r.url}, {len(body)} символів, "
              f"title: {(title.group(1).strip()[:60] if title else '-')}")
        seen = set()
        for m in re.finditer(r"招聘|加入我们|加入智谱|诚聘|社会招聘|校园招聘|join[-_ ]?us|career|jobs\.|mokahr|feishu|zhiye|hotjob",
                             body, re.I):
            ctx = re.sub(r"\s+", " ", body[max(0, m.start() - 110): m.start() + 170])
            key = ctx[90:150]
            if key in seen:
                continue
            seen.add(key)
            show(m.group(0), ctx, 280)
            if len(seen) >= 14:
                break


def moka(org: str) -> None:
    print(f"\n===== MokaHR: {org} =====")
    try:
        r = requests.get(f"https://app.mokahr.com/social-recruitment/{org}", headers=HEADERS, timeout=TIMEOUT)
    except Exception as ex:
        print(f"  {type(ex).__name__}: {str(ex)[:120]}")
        return
    print(f"  {r.status_code} -> {r.url}")
    for blob in re.findall(r"""=\s*["']({&quot;.*?})["']""", r.text, re.S):
        try:
            data = json.loads(htmllib.unescape(blob))
        except ValueError:
            continue
        if isinstance(data, dict) and "jobStats" in data:
            print("  jobStats:", json.dumps(data.get("jobStats"), ensure_ascii=False)[:1500])
            print("  вбудовано вакансій:", len(data.get("jobs") or []), "| ключі:", sorted(data)[:40])
            for j in (data.get("jobs") or [])[:3]:
                print("   ", json.dumps({k: j.get(k) for k in ("id", "title", "status", "openedAt", "zhineng",
                                                                 "commitment", "department")}, ensure_ascii=False)[:300])


def zhipu_chunks() -> None:
    """Куди ведуть кнопки «社会招聘 / 校园招聘» на zhipuai.cn/zh/joinus: адреси зі скриптів сторінки."""
    print("\n===== Zhipu: адреси у скриптах сторінки joinus =====")
    base = "https://www.zhipuai.cn"
    try:
        page = requests.get(f"{base}/zh/joinus", headers=HEADERS, timeout=TIMEOUT).text
    except Exception as ex:
        print(f"  {type(ex).__name__}: {str(ex)[:120]}")
        return
    chunks = re.findall(r'''src=["']([^"']*_next/static/chunks/[^"']+\.js)["']''', page)
    chunks = sorted(set(chunks), key=lambda c: ("joinus" not in c, c))[:25]
    urls: dict[str, str] = {}
    for c in chunks:
        try:
            js = requests.get(base + c if c.startswith("/") else c, headers=HEADERS, timeout=TIMEOUT).text
        except Exception as ex:
            print(f"  {c[-50:]}: {type(ex).__name__}")
            continue
        for m in re.finditer(r'''https?://[^\s"'`<>\\)]+''', js):
            u = m.group(0)
            if re.search(r"job|career|recruit|hire|hr|moka|feishu|zhiye|zhaopin|beisen|talent|campus", u, re.I):
                urls.setdefault(u, c[-40:])
        if "joinus" in c:
            for m in re.finditer(r"window\.open\(|social_recruitment|campus_recruitment", js):
                show("joinus js", js[max(0, m.start() - 200): m.start() + 300], 500)
    for u, c in sorted(urls.items())[:40]:
        print(f"    {u[:200]}   [{c}]")
    for m in re.finditer(r'''https?:\\*/\\*/[^\s"'`<>)]{0,80}(?:job|career|recruit|moka|feishu|zhiye|hotjob|talent)[^\s"'`<>)]{0,120}''', page, re.I):
        print(f"    у HTML: {m.group(0)[:220]}")


def main() -> int:
    zhipu_chunks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
