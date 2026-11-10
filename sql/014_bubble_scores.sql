-- =====================================================================
-- 014_bubble_scores.sql
-- Бали індексу крихкості бульбашки ШІ (v0). Рахує metrics/bubble.py.
-- Бал = процентиль значення ряду серед усієї його попередньої історії (0-100, більше = напруженіше).
-- =====================================================================
BEGIN;
INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('bubble_fragility', 'Індекс крихкості бульбашки ШІ', 'AI bubble fragility index', 'level',
   'середнє балів bubble_score_*', NULL, 'score 0-100', 'metrics/bubble.py', 'daily', 'bubble',
   'v0: рівні ваги, не перевірено. numerator = скільки складників у середньому, denominator = скільки всього.'),
  ('bubble_score_credit', 'Бал: кредитний спред Baa', 'Score: Baa credit spread', 'level',
   'процентиль fred_baa10y серед попередньої історії', NULL, 'score 0-100', 'metrics/bubble.py', 'daily', 'bubble', NULL),
  ('bubble_score_hy', 'Бал: спред високодохідних облігацій', 'Score: high-yield spread', 'level',
   'процентиль fred_hy_oas серед попередньої історії', NULL, 'score 0-100', 'metrics/bubble.py', 'daily', 'bubble',
   'Історія FRED лише з 2023-11, тож бал з''являється з кінця 2024.'),
  ('bubble_score_rate10y', 'Бал: дохідність 10-річних облігацій', 'Score: 10-year yield', 'level',
   'процентиль fred_ust10y серед попередньої історії', NULL, 'score 0-100', 'metrics/bubble.py', 'daily', 'bubble', NULL),
  ('bubble_score_policy', 'Бал: ставка ФРС', 'Score: fed funds rate', 'level',
   'процентиль fred_fed_funds серед попередньої історії', NULL, 'score 0-100', 'metrics/bubble.py', 'daily', 'bubble', NULL),
  ('bubble_score_devjobs', 'Бал: вакансії розробників відносно всіх', 'Score: developer postings vs all postings', 'level',
   'обернений процентиль indeed_softdev_postings / indeed_total_postings (US)', NULL, 'score 0-100',
   'metrics/bubble.py', 'daily', 'shared', 'Менше розробників відносно ринку праці = вищий бал.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('metrics_bubble', 'metrics/bubble.py', 'fct_metric_values', 'file', 24, 'Розрахунок з уже зібраних рядів FRED')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('014_bubble_scores') ON CONFLICT DO NOTHING;
COMMIT;
