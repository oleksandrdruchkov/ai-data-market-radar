-- =====================================================================
-- 019_indeed_ai_tracker.sql
-- Частка вакансій зі згадкою ШІ (Indeed Hiring Lab AI Tracker) - ряд «фахівці ШІ»
-- для зв'язку зі здатностями моделей-лідерів і фінансуванням.
-- Значення пише collectors/indeed_ai_tracker.py; перший запуск - уся історія файлу.
-- =====================================================================
BEGIN;

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('indeed_ai_share', 'Частка вакансій зі згадкою ШІ (Indeed)', 'Share of job postings mentioning AI (Indeed)', 'ratio',
   'вакансії з термінами ШІ в назві чи описі', 'усі вакансії на Indeed', 'percent',
   'Indeed Hiring Lab AI Tracker (github.com/hiring-lab/ai-tracker, CC BY 4.0)', 'daily', 'shared',
   'Ковзне 7-денне середнє, репозиторій оновлюється щомісяця. Рахує ключові слова, а не посади ШІ-фахівців; зміни правил оформлення вакансій можуть зсувати ряд.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('indeed_ai_tracker', 'collectors/indeed_ai_tracker.py', 'fct_metric_values', 'api', 24 * 35,
   'CSV з GitHub без ключа; джерело оновлюється раз на місяць - нові точки з''являються стрибком')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('019_indeed_ai_tracker') ON CONFLICT DO NOTHING;
COMMIT;
