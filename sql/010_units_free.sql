-- =====================================================================
-- 010_units_free.sql
-- Одиниця виміру в записах кола лідерів більше не обмежена коротким списком:
-- картки пишуть «task», «session», «transcript» тощо. На розрахунок вона не впливає.
-- =====================================================================
BEGIN;
ALTER TABLE fct_leader_action_rates DROP CONSTRAINT IF EXISTS fct_leader_action_rates_unit_check;
ALTER TABLE fct_leader_action_rates DROP CONSTRAINT IF EXISTS ck_unit_len;
ALTER TABLE fct_leader_action_rates ADD CONSTRAINT ck_unit_len CHECK (length(unit) BETWEEN 1 AND 40);
INSERT INTO ops_schema_migrations (version) VALUES ('010_units_free') ON CONFLICT DO NOTHING;
COMMIT;
