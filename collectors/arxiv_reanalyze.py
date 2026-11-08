"""
collectors/arxiv_reanalyze.py
Разовий переаналіз статей ArXiv, які колись записав аварійний фолбек
(extraction_method = 'legacy_fallback': роль «AI Systems Engineer», опис = назва статті).

Що робить:
  1. бере з fct_arxiv_signals записи з потрібним extraction_method;
  2. одним запитом до ArXiv API (id_list) підтягує повні анотації - у старих рядках їх немає;
  3. проганяє через той самий промпт і каскад, що й щоденний збирач arxiv.py,
     і оновлює ті самі рядки (first_seen_at і verified не чіпаються).

Якщо Gemini не відповість для частини статей, вони стануть «відкладеними» з source='arxiv',
і щоденний збирач arxiv.py доопрацює їх сам у наступних запусках.

Змінні: REANALYZE_METHOD=legacy_fallback   REANALYZE_LIMIT=50
Запуск: python -m collectors.arxiv_reanalyze   (або GitHub Actions -> Reanalyze ArXiv -> Run workflow)
"""

from __future__ import annotations

import os

from core import RawItem
from collectors.arxiv import ArxivSignals, _get_with_retry, parse_feed


class ArxivReanalyze(ArxivSignals):
    run_label = "arxiv_reanalyze"     # окремо в журналі, щоб не збивати статистику щоденного збору
    collector_version = "reanalyze-1"
    reprocess_limit = 0               # відкладені добере щоденний arxiv.py
    allow_empty = True                # повторний запуск, коли все вже переаналізовано, - не помилка

    def fetch(self):
        method = os.getenv("REANALYZE_METHOD", "legacy_fallback")
        limit = int(os.getenv("REANALYZE_LIMIT", "50"))
        rows = self.db.select(self.fact_table, "arxiv_id", eq={"extraction_method": method},
                              order="published_date", limit=limit)
        ids = [r["arxiv_id"] for r in rows]
        self.log.info(f"До переаналізу ({method}): {len(ids)}")
        if not ids:
            return

        papers = parse_feed(_get_with_retry({"id_list": ",".join(ids), "max_results": len(ids)}).content)
        found = {p["arxiv_id"] for p in papers}
        missing = sorted(set(ids) - found)
        if missing:
            self.log.warning(f"ArXiv не повернув {len(missing)}: {missing}")

        wanted = set(ids)
        for p in papers:
            if p["arxiv_id"] not in wanted:   # ArXiv повертає службовий запис «Error» для невідомих id
                self.log.warning(f"Пропускаю неочікуваний запис {p['arxiv_id']}")
                continue
            if not p["summary"]:
                self.log.warning(f"{p['arxiv_id']}: порожня анотація, пропускаю")
                continue
            yield RawItem(external_id=p["arxiv_id"], payload=p,
                          content_key=f"{p['title']}|{p['summary']}")


if __name__ == "__main__":
    ArxivReanalyze().run()
