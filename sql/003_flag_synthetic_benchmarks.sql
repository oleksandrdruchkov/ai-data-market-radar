-- =====================================================================
-- 003_flag_synthetic_benchmarks.sql  (ВАШЕ РІШЕННЯ - див. README_MIGRATION.md)
-- fetch_benchmarks.py рахував T50/T80 і c_score за формулою від coding-балу Arena
-- (T50 = coding/100 * 17.5, T80 = T50 * 0.32), але записував їх як is_synthetic = false
-- і source_url = metr.org. METR цих значень не вимірював.
-- Цей файл нічого не видаляє: лише чесно позначає такі рядки як синтетичні.
-- evaluate_risks.py читає лише is_synthetic = false, тож після цього він не рахуватиме
-- Monte Carlo на вигаданих даних (і поки що не матиме що рахувати).
-- =====================================================================
BEGIN;
UPDATE fct_metr_horizons
   SET is_synthetic = true
 WHERE source_url = 'https://metr.org/evals' AND is_synthetic = false;

UPDATE fct_pathway_capabilities
   SET is_synthetic = true
 WHERE benchmark_name = 'Frontier Evals Automated' AND is_synthetic = false;

INSERT INTO ops_schema_migrations (version) VALUES ('003_flag_synthetic_benchmarks') ON CONFLICT DO NOTHING;
COMMIT;
