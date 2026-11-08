-- =====================================================================
-- 004_autonomy_horizons.sql
-- Горизонти автономності на спільному каркасі. Безпечно й ідемпотентно, як 001.
-- Потрібна вже застосована 001_core_framework.sql.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

-- 1. Спільні поля фактів
DO $$ BEGIN PERFORM radar_add_fact_columns('fct_autonomy_horizons'); END $$;
DO $$ BEGIN PERFORM radar_add_fact_columns('fct_capability_index');  END $$;

-- 2. Заповнення для наявних рядків. created_at, якщо така колонка є, - справжня «перша поява».
DO $$
DECLARE t text; has_created boolean;
BEGIN
    FOREACH t IN ARRAY ARRAY['fct_autonomy_horizons','fct_capability_index'] LOOP
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = t AND column_name = 'created_at')
          INTO has_created;
        EXECUTE format($f$
            UPDATE %1$I SET
                first_seen_at     = COALESCE(first_seen_at, %2$s, now()),
                last_seen_at      = COALESCE(last_seen_at,  %2$s, now()),
                event_date        = COALESCE(event_date, release_date::date),
                collection_method = COALESCE(collection_method, 'file'),
                extraction_method = COALESCE(extraction_method, 'legacy'),
                prompt_version    = COALESCE(prompt_version, 'legacy')
            WHERE first_seen_at IS NULL OR extraction_method IS NULL
        $f$, t, CASE WHEN has_created THEN 'created_at' ELSE 'NULL::timestamptz' END);
        EXECUTE format('ALTER TABLE %I ALTER COLUMN first_seen_at SET DEFAULT now(), '
                       'ALTER COLUMN last_seen_at SET DEFAULT now()', t);
    END LOOP;
END $$;

-- 3. Реєстр джерел
INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('epoch_metr', 'collectors/epoch_horizons.py', 'fct_autonomy_horizons', 'file', 24,
   'METR via Epoch AI. METR більше не оновлює виміри (остання сторінка 2026-09-08)'),
  ('epoch_eci',  'collectors/epoch_horizons.py', 'fct_capability_index',  'file', 24,
   'Epoch Capabilities Index'),
  ('metrics_autonomy', 'metrics/autonomy.py', 'fct_metric_values', 'file', 24,
   'Розрахунок autonomy_t50_frontier і sai_t_frontier')
ON CONFLICT (source) DO UPDATE
   SET collector = EXCLUDED.collector, fact_table = EXCLUDED.fact_table, notes = EXCLUDED.notes;

-- 4. Показники
INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def, unit,
                         source, frequency, method_version, description) VALUES
  ('autonomy_t50_frontier', 'Горизонт автономності T50 моделі-лідера', 'Frontier T50 time horizon',
   'level', 'max(METR T50, години) серед моделей з release_date <= кінець місяця', NULL, 'hours',
   'METR via Epoch AI (CC BY 4.0)', 'monthly', 'v1',
   'Межі - довірчий інтервал моделі-рекордсменки. Понад 16 год (стеля набору задач METR) - is_estimate. '
   'Ряд закінчується місяцем останнього виміру.'),
  ('sai_t_frontier', 'SAI_T: довжина автономної гілки, % від 1 людино-року', 'SAI_T, % of one human-year',
   'level', '100 * log10(1 + T50_хв)', 'log10(124 800) - еталон 1 людино-рік = 2 080 год', '%',
   'METR via Epoch AI (CC BY 4.0)', 'monthly', 'v1',
   'Логарифмічна шкала: 100% = модель виконує завдання довжиною в людино-рік з успіхом 50%.')
ON CONFLICT (metric_id) DO UPDATE SET
   name_ua = EXCLUDED.name_ua, name_en = EXCLUDED.name_en, kind = EXCLUDED.kind,
   numerator_def = EXCLUDED.numerator_def, denominator_def = EXCLUDED.denominator_def,
   unit = EXCLUDED.unit, source = EXCLUDED.source, frequency = EXCLUDED.frequency,
   description = EXCLUDED.description;

INSERT INTO ops_schema_migrations (version) VALUES ('004_autonomy_horizons') ON CONFLICT DO NOTHING;
COMMIT;
