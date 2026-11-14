-- =====================================================================
-- 020_arxiv_counts.sql
-- Кількість статей ШІ на ArXiv за напрямами, щомісяця, без аналізу моделлю.
-- Значення пише collectors/arxiv_counts.py (перший запуск - з 2023-01).
-- Частки напрямів не складаються в 100 %: одна стаття може відповідати кільком.
-- =====================================================================
BEGIN;

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('arxiv_papers_total', 'Статті ШІ на ArXiv за місяць', 'AI papers on ArXiv per month', 'flow',
   'статті категорій cs.AI, cs.LG, cs.CL, cs.RO, cs.MA, подані за місяць', NULL, 'count',
   'arXiv API (totalResults)', 'monthly', 'shared',
   'Поточний місяць неповний (is_estimate). arXiv дописує статті із запізненням - два останні місяці перераховуються.'),
  ('arxiv_share_agents', 'Частка статей: агенти, що діють самі', 'Share of papers: autonomous agents', 'ratio',
   'статті з фразами LLM agent(s), autonomous agent(s), agentic, tool use в анотації', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Напрям «газ»: самостійність моделей.'),
  ('arxiv_share_ai_science', 'Частка статей: ШІ веде дослідження сам', 'Share of papers: AI doing research itself', 'ratio',
   'AI scientist, automated scientific discovery, autonomous/automated research, self-improving, recursive self-improvement', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Напрям «газ»: ШІ, що прискорює власний розвиток.'),
  ('arxiv_share_robots', 'Частка статей: роботи і фізичний світ', 'Share of papers: robots and the physical world', 'ratio',
   'robot, robotic, embodied, vision-language-action, humanoid', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Напрям «газ»: вихід ШІ у фізичний світ.'),
  ('arxiv_share_reasoning', 'Частка статей: міркування', 'Share of papers: reasoning', 'ratio',
   'test-time compute, chain(-)of(-)thought, reasoning model(s)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Здатність довше й глибше думати над завданням.'),
  ('arxiv_share_safety', 'Частка статей: безпека і контроль', 'Share of papers: safety and control', 'ratio',
   'AI safety, AI alignment, interpretability, red teaming, jailbreak, oversight', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Напрям «гальма»: контроль над моделями.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('arxiv_counts', 'collectors/arxiv_counts.py', 'fct_metric_values', 'api', 24,
   'arXiv API, лише totalResults; не частіше 1 запиту на 3 с; перший запуск ~15 хв')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('020_arxiv_counts') ON CONFLICT DO NOTHING;
COMMIT;
