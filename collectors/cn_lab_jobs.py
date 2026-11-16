"""
collectors/cn_lab_jobs.py
Відкриті вакансії китайських лабораторій-лідерів (лідери за ECI) -> fct_metric_values.

  cn_lab_jobs_<лабораторія>   скільки вакансій відкрито на сторінці найму лабораторії на дату
  cn_labs_open_jobs           сума за всіма лабораторіями списку (лише коли відповіли всі)

Це кількість оголошень на сторінках найму конкретних компаній, а не частка ринку: ряд не
усереднюється з Indeed AI Tracker і на лінію «Фахівці ШІ» не лягає. Рахуються всі відкриті
вакансії сторінки соціального найму - технічні й нетехнічні, разом зі стажуваннями, якщо
компанія публікує їх там само. Значення - знімок на дату запуску (UTC); історії до першого
запуску немає, пропущений день лишається пропуском.

Звідки число (перевірено tools/probe_cn_careers.py, 2026-11-16):
  MokaHR  сторінка app.mokahr.com/social-recruitment/<org>/<site>, вбудований лічильник jobStats.total
          (DeepSeek: high-flyer/140576; Moonshot: moonshot/148506)
  Feishu  <host>/api/v1/search/job/posts, поле data.count; перед запитом сайт видає токен
          захисту форми (/api/v1/csrf/token). MiniMax: vrfi1sk8a0.jobs.feishu.cn/379481
Лише читання публічних сторінок; жодних дій з акаунтами кандидатів.

Не входять: Zhipu (Z.ai) - сторінку зі списком вакансій ще не знайдено; Alibaba - портал найму
всієї корпорації, а не лабораторії.

Сума має сенс лише для незмінного набору лабораторій: набір записано в method_version
(«v1:deepseek+minimax+moonshot»). Додали лабораторію - версія змінилась, і на графіку це шов.

Змінні: CN_LAB_JOBS="deepseek,moonshot,minimax"  (які лабораторії збирати)
Запуск: python -m collectors.cn_lab_jobs            (запис у базу)
        python -m collectors.cn_lab_jobs --dry-run  (лише друк, без бази)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, date
from urllib.parse import unquote

from core.http import get_with_retry
from collectors._metric_series import MetricSeriesCollector, SeriesResult
from collectors.jobs_deepseek import embedded_state

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MarketRadarBot/2.0; "
                         "+https://github.com/oleksandrdruchkov/ai-data-market-radar)",
           "Accept-Language": "zh-CN,zh;q=0.9"}
TOTAL_ID = "cn_labs_open_jobs"
REGION = "CN"

LABS: dict[str, dict] = {
    "deepseek": {"lab": "DeepSeek", "platform": "mokahr", "org": "high-flyer", "site": "140576"},
    "moonshot": {"lab": "Moonshot", "platform": "mokahr", "org": "moonshot", "site": "148506"},
    "minimax": {"lab": "MiniMax", "platform": "feishu", "host": "vrfi1sk8a0.jobs.feishu.cn", "path": "379481"},
}


def metric_id(key: str) -> str:
    return f"cn_lab_jobs_{key}"


def moka_total(page: str) -> int:
    """Чиста функція: лічильник jobStats.total зі сторінки MokaHR. Немає лічильника - помилка, а не нуль."""
    total = (embedded_state(page).get("jobStats") or {}).get("total")
    if isinstance(total, bool) or not isinstance(total, (int, str)) or not str(total).isdigit():
        raise ValueError(f"MokaHR: немає jobStats.total (отримано {total!r})")
    return int(total)


def feishu_count(body: dict) -> int:
    """Чиста функція: data.count з відповіді пошуку Feishu. Помилка сайту або немає count - виняток."""
    if not isinstance(body, dict) or body.get("code") != 0:
        raise ValueError(f"Feishu відповів помилкою: {str(body)[:200]}")
    count = (body.get("data") or {}).get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"Feishu: немає data.count (отримано {count!r})")
    return count


def total_series(per_lab: list[SeriesResult], method_version_labs: list[str]) -> SeriesResult:
    """Чиста функція: сума за лабораторіями на одну дату. Хоч одна не відповіла - суми немає."""
    res = SeriesResult(metric_id=TOTAL_ID, region=REGION)
    failed = [s.metric_id for s in per_lab if s.error or not s.points]
    if failed or not per_lab:
        res.error = "немає даних лабораторій: " + (", ".join(failed) or "порожній список")
        return res
    days = {s.points[0][0] for s in per_lab}
    if len(days) != 1:
        res.error = f"різні дати рядів: {sorted(days)}"
        return res
    day = days.pop()
    res.points = [(day, float(sum(s.points[0][1] for s in per_lab)))]
    res.extra = {day: {"denominator": len(method_version_labs)}}     # скільки лабораторій у сумі
    return res


def fetch_moka(org: str, site: str) -> int:
    page = get_with_retry(f"https://app.mokahr.com/social-recruitment/{org}/{site}", headers=HEADERS, timeout=60).text
    return moka_total(page)


def fetch_feishu(host: str, path: str) -> int:
    import requests
    base = f"https://{host}"
    s = requests.Session()
    s.headers.update({**HEADERS, "website-path": path, "Referer": f"{base}/{path}", "Origin": base})
    r = s.post(f"{base}/api/v1/csrf/token", json={"portal_entrance": 1}, timeout=60)
    r.raise_for_status()
    token = s.cookies.get("atsx-csrf-token") or ((r.json().get("data") or {}).get("token"))
    if not token:
        raise ValueError("Feishu: сайт не видав токен захисту форми")
    r = s.post(f"{base}/api/v1/search/job/posts",
               params={"keyword": "", "limit": 1, "offset": 0, "portal_type": 6, "portal_entrance": 1},
               json={"keyword": "", "limit": 1, "offset": 0, "portal_type": 6, "portal_entrance": 1},
               headers={"x-csrf-token": unquote(token)}, timeout=60)
    r.raise_for_status()
    return feishu_count(r.json())


class CnLabJobs(MetricSeriesCollector):
    source = "cn_lab_jobs"
    collector_version = "1"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.keys = self.lab_keys()
        self.method_version = "v1:" + "+".join(sorted(self.keys))

    @staticmethod
    def lab_keys() -> list[str]:
        raw = [k.strip().lower() for k in os.getenv("CN_LAB_JOBS", ",".join(LABS)).split(",") if k.strip()]
        unknown = [k for k in raw if k not in LABS]
        if unknown:
            raise ValueError(f"CN_LAB_JOBS: невідомі лабораторії {unknown}; відомі: {sorted(LABS)}")
        return raw

    def count(self, key: str) -> int:
        lab = LABS[key]
        if lab["platform"] == "mokahr":
            return fetch_moka(lab["org"], lab["site"])
        return fetch_feishu(lab["host"], lab["path"])

    def fetch_series(self) -> list[SeriesResult]:
        today: date = datetime.now(timezone.utc).date()
        per_lab = []
        for key in self.keys:
            res = SeriesResult(metric_id=metric_id(key), region=REGION)
            try:
                res.points = [(today, float(self.count(key)))]
            except Exception as e:
                res.error = f"{LABS[key]['lab']}: {type(e).__name__}: {str(e)[:200]}"
            per_lab.append(res)
        return per_lab + [total_series(per_lab, self.keys)]


def dry_run() -> int:
    c = CnLabJobs.__new__(CnLabJobs)
    c.keys = CnLabJobs.lab_keys()
    bad = 0
    for s in c.fetch_series():
        print(f"{s.metric_id}: {s.points[0][1]:.0f}" if s.points else f"{s.metric_id}: ПОМИЛКА {s.error}")
        bad += 0 if s.points else 1
    return 1 if bad else 0


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        sys.exit(dry_run())
    CnLabJobs().run()
