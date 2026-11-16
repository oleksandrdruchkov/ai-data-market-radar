-- =====================================================================
-- 029_cn_lab_jobs.sql
-- Відкриті вакансії китайських лабораторій-лідерів (DeepSeek, Moonshot, Zhipu, MiniMax).
-- Значення пише collectors/cn_lab_jobs.py: знімок кількості вакансій на сторінці найму на дату.
-- Це кількість оголошень конкретних компаній, а не частка ринку: з Indeed AI Tracker
-- не усереднюється і на лінію «Фахівці ШІ» не лягає.
-- Ідемпотентно. Потрібна 011 (dim_metrics, fct_metric_values).
-- =====================================================================
BEGIN;

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('cn_lab_jobs_deepseek', 'Відкриті вакансії DeepSeek', 'Open job postings at DeepSeek', 'stock',
   'лічильник jobStats.total сторінки найму', NULL, 'count', 'MokaHR (app.mokahr.com/social-recruitment/high-flyer/140576)',
   'daily', 'shared', 'Усі відкриті вакансії сторінки соціального найму на дату запуску.'),
  ('cn_lab_jobs_moonshot', 'Відкриті вакансії Moonshot (Kimi)', 'Open job postings at Moonshot (Kimi)', 'stock',
   'лічильник jobStats.total сторінки найму', NULL, 'count', 'MokaHR (app.mokahr.com/social-recruitment/moonshot/148506)',
   'daily', 'shared', 'Усі відкриті вакансії сторінки соціального найму на дату запуску.'),
  ('cn_lab_jobs_zhipu', 'Відкриті вакансії Zhipu (Z.ai)', 'Open job postings at Zhipu (Z.ai)', 'stock',
   'лічильник jobStats.total сторінки найму', NULL, 'count', 'MokaHR (app.mokahr.com/social-recruitment/zphz/148983)',
   'daily', 'shared', 'Усі відкриті вакансії сторінки соціального найму на дату запуску.'),
  ('cn_lab_jobs_minimax', 'Відкриті вакансії MiniMax', 'Open job postings at MiniMax', 'stock',
   'поле count пошуку вакансій на сторінці найму', NULL, 'count', 'Feishu (vrfi1sk8a0.jobs.feishu.cn/379481)',
   'daily', 'shared', 'Усі відкриті вакансії сторінки найму на дату запуску, разом зі стажуваннями.'),
  ('cn_labs_open_jobs', 'Відкриті вакансії китайських лабораторій-лідерів', 'Open job postings at leading Chinese labs', 'stock',
   'сума cn_lab_jobs_* за набором лабораторій з method_version', 'кількість лабораторій у сумі', 'count',
   'сторінки найму лабораторій (MokaHR, Feishu)', 'daily', 'shared',
   'Пишеться лише коли відповіли всі лабораторії набору. Набір змінився - змінилась method_version, ряд має шов. Не частка ринку.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('cn_lab_jobs', 'collectors/cn_lab_jobs.py', 'fct_metric_values', 'scrape', 24,
   'Сторінки найму DeepSeek, Moonshot, Zhipu (MokaHR) і MiniMax (Feishu); без ключів і без моделі')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('029_cn_lab_jobs') ON CONFLICT DO NOTHING;
COMMIT;
