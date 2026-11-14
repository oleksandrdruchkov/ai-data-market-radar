-- =====================================================================
-- 023_deepseek_mokahr.sql
-- Збирач DeepSeek тепер читає офіційну сторінку вакансій на MokaHR, а не ручний список.
-- =====================================================================
BEGIN;
UPDATE ops_sources SET collection_method = 'scrape',
       notes = 'Офіційна сторінка вакансій DeepSeek/High-Flyer на MokaHR; список вбудований у HTML, 1 запит на день'
WHERE source = 'deepseek_careers';
INSERT INTO ops_schema_migrations (version) VALUES ('023_deepseek_mokahr') ON CONFLICT DO NOTHING;
COMMIT;
