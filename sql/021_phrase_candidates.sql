-- =====================================================================
-- 021_phrase_candidates.sql
-- Кандидати у фрази напрямів ArXiv: нові навички з fct_arxiv_signals, яких ще не ловить
-- жодна фраза. Готує metrics/arxiv_phrase_candidates.py раз на місяць; рішення приймає
-- людина на сторінці перевірки (review_ui.py).
--   new      - чекає на рішення
--   added    - додано до напряму direction; collectors/arxiv_counts.py бере phrase у запит
--              і перераховує історію (змінюється відбиток списку фраз)
--   rejected - не стосується напрямів; більше не пропонується
-- =====================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS ops_phrase_candidates (
    skill_norm          text PRIMARY KEY,
    phrase              text NOT NULL,
    n_signals           integer NOT NULL DEFAULT 0,
    n_arxiv_month       integer,
    suggested_direction text,
    example_titles      jsonb NOT NULL DEFAULT '[]'::jsonb,
    first_month         date,
    last_month          date,
    status              text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'added', 'rejected')),
    direction           text CHECK (direction IS NULL OR direction IN ('agents', 'ai_science', 'robots', 'reasoning', 'safety')),
    decided_at          timestamptz,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'added' OR direction IS NOT NULL)
);

ALTER TABLE ops_phrase_candidates ENABLE ROW LEVEL SECURITY;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('arxiv_phrase_candidates', 'metrics/arxiv_phrase_candidates.py', 'ops_phrase_candidates', 'api', 24 * 35,
   'Раз на місяць: навички з fct_arxiv_signals, яких не ловить жодна фраза напрямів')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('021_phrase_candidates') ON CONFLICT DO NOTHING;
COMMIT;
