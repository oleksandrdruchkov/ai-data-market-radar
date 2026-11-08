-- =====================================================================
-- 009_cards_queue_and_keys.sql
--  * ops_documents: статус 'queued' - посилання на картки, знайдені всередині інших карток
--    (основна картка GPT-6 є лише в посиланнях із доповнень, а не на першій сторінці покажчика);
--  * fct_leader_action_rates: ключ за model_key (назва без розділових знаків) і URL документа,
--    щоб «GPT-6 Cyber» і «GPT-6-Cyber» з того самого документа були одним записом.
-- Непідтверджені автоматичні записи видаляються: збирач створить їх заново.
-- Ідемпотентно. Потрібні 005-008.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

ALTER TABLE ops_documents DROP CONSTRAINT IF EXISTS ops_documents_status_check;
ALTER TABLE ops_documents ADD CONSTRAINT ops_documents_status_check
    CHECK (status IN ('queued', 'done', 'no_relevant_pages', 'no_real_use_data', 'failed'));

DELETE FROM fct_leader_action_rates WHERE NOT verified AND verified_by IS NULL;

-- 'GPT-6-Cyber' / 'GPT-6 Cyber' -> 'gpt 6 cyber'
CREATE OR REPLACE FUNCTION radar_model_key(name text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN btrim(regexp_replace(lower(coalesce(name, '')), '[^a-z0-9]+', ' ', 'g'));
END $$;

ALTER TABLE fct_leader_action_rates
    ADD COLUMN IF NOT EXISTS model_key text GENERATED ALWAYS AS (radar_model_key(model_name)) STORED;

ALTER TABLE fct_leader_action_rates DROP CONSTRAINT IF EXISTS ux_leader_action;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ux_leader_action_key') THEN
        ALTER TABLE fct_leader_action_rates
            ADD CONSTRAINT ux_leader_action_key UNIQUE (lab, model_key, source_url, method);
    END IF;
END $$;

INSERT INTO ops_schema_migrations (version) VALUES ('009_cards_queue_and_keys') ON CONFLICT DO NOTHING;
COMMIT;
