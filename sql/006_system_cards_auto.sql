-- =====================================================================
-- 006_system_cards_auto.sql
-- Автоматичний збір системних карток і автоматичне підтвердження записів кола лідерів.
--   * ops_documents - які картки вже оброблено (щоб не завантажувати їх щодня);
--   * verified_by: 'human' | 'auto' - хто підтвердив;
--   * verification_log - що саме перевірено і чому запис не пройшов.
-- Автопідтвердження робить код (див. collectors/_card_verify.py), а не модель:
-- цитата дослівно на сторінці, числа в цитаті, частку рахує код, друга модель згодна.
-- Ідемпотентно. Потрібні 001 і 005.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

ALTER TABLE fct_leader_action_rates
    ADD COLUMN IF NOT EXISTS verified_by       text CHECK (verified_by IN ('human', 'auto')),
    ADD COLUMN IF NOT EXISTS verification_log  jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS extraction_method text,
    ADD COLUMN IF NOT EXISTS raw_item_id       bigint REFERENCES raw_items(raw_id) ON DELETE SET NULL;

-- Записи, які людина вже підтвердила вручну
UPDATE fct_leader_action_rates SET verified_by = 'human' WHERE verified AND verified_by IS NULL;

CREATE TABLE IF NOT EXISTS ops_documents (
    url           text PRIMARY KEY,
    lab           text NOT NULL,
    title         text,
    listed_date   text,
    status        text NOT NULL CHECK (status IN ('done', 'no_relevant_pages', 'no_real_use_data', 'failed')),
    n_records     int NOT NULL DEFAULT 0,
    processed_at  timestamptz NOT NULL DEFAULT now(),
    note          text
);

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('system_cards', 'collectors/system_cards.py', 'fct_leader_action_rates', 'scrape', 24,
   'Системні картки Anthropic і OpenAI: дані реальної роботи, дії поза межами; автопідтвердження кодом')
ON CONFLICT (source) DO NOTHING;

-- Представлення: додаємо, хто підтвердив
CREATE OR REPLACE VIEW v_leader_action_models AS
WITH per_model AS (
    SELECT lab, model_name, max(release_date) AS release_date,
           avg(rate_out) AS rate_out,
           sum(n_total) AS n_total, sum(n_out) AS n_out,
           jsonb_agg(jsonb_build_object(
               'source_doc', source_doc, 'source_url', source_url, 'section', section, 'page', page,
               'method', method, 'unit', unit, 'classifier', classifier,
               'n_total', n_total, 'n_out', n_out, 'rate_out', rate_out,
               'counted', counted, 'excluded', excluded, 'data_origin', data_origin,
               'verified_by', verified_by)
             ORDER BY source_doc) AS sources
    FROM fct_leader_action_rates
    WHERE verified
    GROUP BY lab, model_name
), latest AS (
    SELECT DISTINCT ON (lab) * FROM per_model ORDER BY lab, release_date DESC
)
SELECT l.*,
       CASE WHEN jsonb_array_length(l.sources) = 1 THEN (radar_wilson(l.n_out, l.n_total)).lo END AS ci_low,
       CASE WHEN jsonb_array_length(l.sources) = 1 THEN (radar_wilson(l.n_out, l.n_total)).hi END AS ci_high
FROM latest l
ORDER BY l.lab;

DROP VIEW IF EXISTS v_leader_action_pending;
CREATE VIEW v_leader_action_pending AS
SELECT id, lab, model_name, release_date, section, page, method, rate_out, n_total, n_out,
       data_origin, notes, verification_log
FROM fct_leader_action_rates WHERE NOT verified ORDER BY release_date DESC;

INSERT INTO ops_schema_migrations (version) VALUES ('006_system_cards_auto') ON CONFLICT DO NOTHING;
COMMIT;
