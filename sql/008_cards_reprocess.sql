-- =====================================================================
-- 008_cards_reprocess.sql
-- Версія обробки документа: коли змінюється спосіб відбору сторінок або промпт,
-- збирач системних карток переглядає вже оброблені документи заново.
-- =====================================================================
BEGIN;
ALTER TABLE ops_documents ADD COLUMN IF NOT EXISTS processed_version text;
INSERT INTO ops_schema_migrations (version) VALUES ('008_cards_reprocess') ON CONFLICT DO NOTHING;
COMMIT;
