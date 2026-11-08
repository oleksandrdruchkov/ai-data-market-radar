# Перехід на спільний каркас збирачів

## Що змінилось

```
core/            спільний каркас: db.py, llm.py, base_collector.py, quality.py
collectors/      збирачі: jobs_adzuna.py, jobs_deepseek.py, arxiv.py (+ _jobs_common.py)
collectors/seeds/deepseek_manual.json   3 вакансії DeepSeek, що раніше були вписані в код
sql/001_core_framework.sql              обов'язкова міграція
sql/002_rls_new_tables.sql              рекомендовано (захист нових таблиць)
sql/003_flag_synthetic_benchmarks.sql   ваше рішення (позначити вигадані горизонти)
sql/004_autonomy_horizons.sql           горизонти METR / ECI на каркасі + показники autonomy_t50_frontier, sai_t_frontier
metrics/autonomy.py                     розрахунок показників у fct_metric_values
tests/                                  тести каркаса
```

Видалено (замінено): `main_pipeline.py` → `collectors/jobs_adzuna.py`,
`collector_deepseek.py` → `collectors/jobs_deepseek.py`, `collector_arxiv.py` → `collectors/arxiv.py`.
`app.py` не змінювався і далі працює з тими самими таблицями.

## Порядок запуску

1. **Резервна копія** Supabase (Database → Backups або `pg_dump`).
2. SQL Editor → вставити `sql/001_core_framework.sql` → Run.
   Перевірка: `select * from ops_schema_migrations;` має показати `001_core_framework`.
3. Перевірити, що `SUPABASE_KEY` у GitHub Secrets - це **service_role**. Тоді запустити `sql/002_rls_new_tables.sql`.
4. Закомітити код. У GitHub → Actions → *Run workflow* (ручний запуск).
5. Перевірка після запуску:
   ```sql
   select source, status, items_seen, items_new, items_deferred, llm_calls, llm_cache_hits, error
   from ops_collector_runs order by run_id desc limit 10;
   select * from v_ops_source_freshness;
   select * from v_ops_open_alerts;
   ```

## Що робить міграція 001 з наявними даними

* `fct_vacancies`: Adzuna-рядки `adzuna_us/123` → `adzuna/us:123` (одне джерело, id Adzuna унікальний лише в межах країни).
  Старі рядки отримують `extraction_method = 'legacy'`; `event_date` заповнюється лише для Adzuna
  (у DeepSeek `posted_at` був датою збору, а не публікації).
* `fct_arxiv_signals`: рядки, які записав старий аварійний фолбек
  («Frontier AI Systems» / «AI Systems Engineer»), позначаються `extraction_method = 'legacy_fallback'`.
* `raw_jobs` копіюється в `raw_items` зі статусом `legacy`; сама `raw_jobs` не змінюється.
* `first_seen_at` береться з `created_at` (коли рядок уперше потрапив у базу), для `raw_items` - з `raw_jobs.ingested_at`.

## Правила нового каркаса

* LLM недоступна → запис **відкладається** (`raw_items.status = 'deferred'`) і дообробляється наступними запусками. Вигаданих значень більше немає.
* Відповідь LLM перевіряється схемою: рівень, трек, формат роботи - лише з допустимого списку.
* Той самий текст з тим самим `prompt_version` не тратить квоту двічі (`ops_llm_cache`).
  Змінили промпт → підніміть `PROMPT_VERSION` у збирачі.
* `first_seen_at` ставить база при першій появі; `verified` змінює лише людина.
* Факти закриваються (`is_active = false`) лише якщо джерело дає **повний** список (`tracks_presence = True`)
  і в поточному запуску реально відповіло.
* Критичне попередження (джерело не відповіло / 0 записів / >50% помилок) робить крок у GitHub Actions червоним.

## Новий збирач

```python
from core import BaseCollector, RawItem

class MySource(BaseCollector):
    source = "my_source"
    fact_table = "fct_my_facts"          # спочатку: select radar_add_fact_columns('fct_my_facts');

    def fetch(self):
        for item in ...:
            yield RawItem(external_id=item["id"], payload=item)

    def parse(self, raw):
        res = self.llm.extract(prompt=..., schema=MySchema, prompt_name="my",
                               prompt_version="my_v1", content_hash=raw.content_hash)
        if res is None:
            return None                  # відкласти
        return {..., "extraction_method": res.method, "prompt_version": "my_v1"}

if __name__ == "__main__":
    MySource().run()
```

Плюс рядок в `ops_sources` і крок у `.github/workflows/pipeline_cron.yml`.

## Тести

```bash
python -m pytest -q tests                                   # без бази
RADAR_TEST_PG="-h localhost -p 5432 -U postgres" python -m pytest -q tests   # з локальним Postgres
```
