# Каркас збирачів і міграції бази

Перелік міграцій нижче доповнено до 029 (2026-11-16). Решта - нотатки переходу на спільний каркас.

## Перехід на спільний каркас збирачів

## Що змінилось

```
core/            спільний каркас: db.py, llm.py, base_collector.py, quality.py
collectors/      збирачі: jobs_adzuna.py, jobs_deepseek.py, arxiv.py (+ _jobs_common.py)
collectors/seeds/deepseek_manual.json   3 вакансії DeepSeek, що раніше були вписані в код
sql/001_core_framework.sql              обов'язкова міграція
sql/002_rls_new_tables.sql              рекомендовано (захист нових таблиць)
sql/003_flag_synthetic_benchmarks.sql   ваше рішення (позначити вигадані горизонти)
sql/004_autonomy_horizons.sql           горизонти METR / ECI на каркасі + показники autonomy_t50_frontier, sai_t_frontier
sql/005_leader_actions.sql              коло дій моделей-лідерів (лише дані реальної роботи)
sql/006_system_cards_auto.sql           автоматичний збір системних карток і автопідтвердження
sql/007_leader_by_eci.sql               лідер лабораторії = найвищий ECI
sql/008_cards_reprocess.sql             повторна обробка карток після зміни збирача
sql/009_cards_queue_and_keys.sql        черга посилань між картками; одна модель = один запис (model_key)
sql/010_units_free.sql                  одиниця виміру в записах кола - будь-яка (task, session ...)
sql/011_bubble_metrics.sql              показники індексу крихкості бульбашки ШІ
sql/012_baa10y.sql                      кредитний спред Moody's Baa
sql/013_real_use_only_and_review.sql    на коло - лише реальне використання; рішення людини на сторінці перевірки
sql/014_bubble_scores.sql               бали складників індексу бульбашки
sql/015_market_signals.sql              ринкові сигнали SEC (див. docs/market_signals.md)
sql/016_sec_external_id.sql             ключ подань SEC
sql/017_funding_ladder.sql              драбина фінансування
sql/018_funding_ladder_fix.sql          виправлення драбини фінансування
sql/019_indeed_ai_tracker.sql           Indeed AI Tracker (частка вакансій зі згадкою ШІ)
sql/020_arxiv_counts.sql                лічильники arXiv за фразами (без моделі)
sql/021_phrase_candidates.sql           кандидати фраз для перевірки людиною
sql/022_arxiv_self_improvement.sql      напрям «адаптивність після розгортання»
sql/023_deepseek_mokahr.sql             вакансії DeepSeek через MokaHR
sql/024_arxiv_autonomy_oversight.sql    групи «зростання автономності» / «людський нагляд»
sql/025_arxiv_stop_resistance.sql       напрям «опір зупинці та втручанню людини»
sql/026_circle_units_aliases.sql        коло: без тестів-провокацій, синоніми моделей, окремо за одиницями
sql/027_circle_periods.sql              коло за місяцями: попередні періоди у випадаючому меню
sql/028_indeed_ai_share_monthly.sql     місячна частка вакансій зі згадкою ШІ за країнами (лінія «Фахівці ШІ»)
sql/029_cn_lab_jobs.sql                 відкриті вакансії китайських лабораторій-лідерів (сторінки найму)
collectors/system_cards.py              збирач карток Anthropic / OpenAI
collectors/_card_verify.py              механічна перевірка (цитати, числа, друга модель) - без моделі
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
