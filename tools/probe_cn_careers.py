"""
tools/probe_cn_careers.py
Діагностика: на яких платформах сторінки найму китайських лабораторій-лідерів (лідери за ECI).
Лише читання публічних сторінок (GET), без запису в базу і без жодних дій з акаунтами.

Що робить для кожної адреси зі списку:
  1) GET сторінки: код відповіді, кінцева адреса, заголовок;
  2) шукає в HTML згадки платформ найму (MokaHR, Feishu, Beisen тощо) і посилання зі словами
     career / join / job / 招聘 / 加入;
  3) те саме - у перших скриптах сторінки з того самого сайту (посилання часто зашиті в скрипт).

Запуск: python -m tools.probe_cn_careers
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urljoin, urlparse

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 MarketRadarBot/2.0")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
TIMEOUT = 25
MAX_SCRIPTS = 12

SEEDS: dict[str, list[str]] = {
    "Moonshot": [
        "https://www.moonshot.cn/", "https://www.moonshot.ai/", "https://www.moonshot.cn/jobs",
        "https://www.moonshot.cn/careers", "https://www.kimi.com/",
        "https://moonshot.jobs.feishu.cn/", "https://moonshot.jobs.feishu.cn/index",
        "https://app.mokahr.com/apply/moonshot", "https://app.mokahr.com/social-recruitment/moonshot",
    ],
    "Zhipu": [
        "https://www.zhipuai.cn/", "https://www.zhipuai.cn/joinus", "https://www.zhipuai.cn/join",
        "https://z.ai/", "https://bigmodel.cn/",
        "https://zhipu-ai.jobs.feishu.cn/", "https://zhipu-ai.jobs.feishu.cn/index",
        "https://zhipuai.jobs.feishu.cn/index",
        "https://app.mokahr.com/apply/zhipuai", "https://app.mokahr.com/apply/zhipu",
    ],
    "MiniMax": [
        "https://www.minimaxi.com/", "https://www.minimax.io/", "https://www.minimaxi.com/careers",
        "https://www.minimaxi.com/join", "https://vrfi1sk8a0.jobs.feishu.cn/index",
        "https://minimax.jobs.feishu.cn/index", "https://app.mokahr.com/apply/minimax",
    ],
    "Alibaba": [
        "https://talent.alibaba.com/", "https://talent-holding.alibaba.com/",
        "https://careers.aliyun.com/", "https://talent.alibaba.com/off-campus/position-list?lang=zh",
    ],
}

ATS_RE = re.compile(
    r"""(?:https?:)?//[^\s"'<>\\)]*?(?:mokahr\.com|jobs\.feishu\.cn|jobs\.larksuite\.com|zhiye\.com|beisen\.com|"""
    r"""hotjob\.cn|dayee\.com|lever\.co|greenhouse\.io|ashbyhq\.com|workable\.com|zhipin\.com|liepin\.com|"""
    r"""talent\.[a-z-]+\.com|careers?\.[a-z-]+\.(?:com|cn|ai|io))[^\s"'<>\\)]*""", re.I)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["'][^>]*>([^<]{0,60})""", re.I)
WORD_RE = re.compile(r"career|join|job|recruit|hiring|招聘|加入|诚聘|人才", re.I)
SCRIPT_RE = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def get(url: str) -> requests.Response | None:
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except Exception as ex:                                    # мережа, сертифікат, тайм-аут
        print(f"    ! {type(ex).__name__}: {str(ex)[:140]}")
        return None


def scan(text: str) -> set[str]:
    return {m.group(0).rstrip(".,;") for m in ATS_RE.finditer(text)}


def probe(url: str) -> None:
    print(f"\n  GET {url}")
    r = get(url)
    if r is None:
        return
    body = r.text or ""
    title = TITLE_RE.search(body)
    print(f"    {r.status_code}  -> {r.url}  ({len(body)} символів)  "
          f"title: {(title.group(1).strip()[:80] if title else '-')}")
    found = scan(body)
    links = {(urljoin(r.url, h), t.strip()) for h, t in HREF_RE.findall(body)
             if WORD_RE.search(h) or WORD_RE.search(t)}
    host = urlparse(r.url).netloc
    scripts = [urljoin(r.url, s) for s in SCRIPT_RE.findall(body)]
    scripts = [s for s in scripts if urlparse(s).netloc.split(".")[-2:] == host.split(".")[-2:]][:MAX_SCRIPTS]
    for s in scripts:
        rs = get(s)
        if rs is not None and rs.status_code == 200:
            found |= scan(rs.text or "")
    for f in sorted(found)[:25]:
        print(f"    платформа: {f[:200]}")
    for h, t in sorted(links)[:15]:
        print(f"    посилання: {h[:160]}  [{t[:40]}]")
    # ознаки вбудованих даних списку вакансій
    for key in ("jobStats", "aesIv", "job_post_list", "jobPostList", "positionList", "window.__INITIAL"):
        if key in body:
            print(f"    у сторінці є ключ: {key}")


def main() -> int:
    for lab, urls in SEEDS.items():
        print(f"\n===== {lab} =====")
        for u in urls:
            probe(u)
    return 0


if __name__ == "__main__":
    sys.exit(main())
