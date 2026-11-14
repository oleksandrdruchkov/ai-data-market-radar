-- =====================================================================
-- 022_arxiv_self_improvement.sql
-- Напрям ai_science розділено на два:
--   ai_science        ШІ веде наукові дослідження (AI scientist, автоматизовані відкриття)
--   self_improvement  ШІ вдосконалює себе (self-improving, recursive self-improvement ...)
-- Список фраз змінився -> збирач arxiv_counts перераховує всю історію новим відбитком.
-- =====================================================================
BEGIN;

UPDATE dim_metrics SET
    name_ua = 'Частка статей: ШІ веде наукові дослідження',
    name_en = 'Share of papers: AI doing scientific research',
    description = 'Напрям «газ»: ШІ, що сам веде дослідження й відкриття. Без self-improving - це окремий напрям.'
WHERE metric_id = 'arxiv_share_ai_science';

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('arxiv_share_self_improvement', 'Частка статей: ШІ вдосконалює себе', 'Share of papers: AI improving itself', 'ratio',
   'фрази напряму self_improvement (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared',
   'Напрям «газ»: методи, де модель покращує власні відповіді чи навчання, аж до рекурсивного самовдосконалення.')
ON CONFLICT (metric_id) DO NOTHING;

ALTER TABLE ops_phrase_candidates DROP CONSTRAINT IF EXISTS ops_phrase_candidates_direction_check;
ALTER TABLE ops_phrase_candidates ADD CONSTRAINT ops_phrase_candidates_direction_check CHECK (
    direction IS NULL OR direction IN ('agents', 'ai_science', 'self_improvement', 'robots', 'reasoning', 'safety'));

INSERT INTO ops_schema_migrations (version) VALUES ('022_arxiv_self_improvement') ON CONFLICT DO NOTHING;
COMMIT;
