-- =====================================================================
-- 002_rls_new_tables.sql  (НЕОБОВ'ЯЗКОВО, але рекомендовано)
-- Вмикає Row Level Security на нових таблицях: публічний ключ (anon) зможе лише
-- ЧИТАТИ показники та журнал, але не писати.
--
-- ПЕРЕД ЗАПУСКОМ перевірте: у GitHub Secrets SUPABASE_KEY для збирачів має бути
-- ключ service_role (він обходить RLS). Якщо там anon-ключ, після цього файлу
-- збирачі не зможуть писати. Streamlit може лишатися на anon-ключі.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

ALTER TABLE raw_items          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops_llm_cache      ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops_collector_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops_quality_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops_sources        ENABLE ROW LEVEL SECURITY;
ALTER TABLE dim_metrics        ENABLE ROW LEVEL SECURITY;
ALTER TABLE fct_metric_values  ENABLE ROW LEVEL SECURITY;

-- raw_items і ops_llm_cache: без політик => лише service_role
DROP POLICY IF EXISTS read_all ON ops_collector_runs;
CREATE POLICY read_all ON ops_collector_runs FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS read_all ON ops_quality_alerts;
CREATE POLICY read_all ON ops_quality_alerts FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS read_all ON ops_sources;
CREATE POLICY read_all ON ops_sources        FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS read_all ON dim_metrics;
CREATE POLICY read_all ON dim_metrics        FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS read_all ON fct_metric_values;
CREATE POLICY read_all ON fct_metric_values  FOR SELECT TO anon, authenticated USING (true);

-- Функцію запису сирих даних може викликати лише service_role
REVOKE EXECUTE ON FUNCTION radar_touch_raw(text, text, text, jsonb, timestamptz) FROM PUBLIC, anon, authenticated;

INSERT INTO ops_schema_migrations (version) VALUES ('002_rls_new_tables') ON CONFLICT DO NOTHING;
COMMIT;
