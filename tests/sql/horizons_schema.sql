-- Копія реальної схеми Supabase (information_schema, 2026-11-08)
CREATE TABLE fct_autonomy_horizons (source text NOT NULL, metric text NOT NULL, model_name text NOT NULL,
  release_date date NOT NULL, value_hours numeric NOT NULL, ci_low numeric, ci_high numeric,
  source_url text, is_synthetic boolean DEFAULT false, PRIMARY KEY (source, metric, model_name));
CREATE TABLE fct_capability_index (source text NOT NULL DEFAULT 'EPOCH_ECI', model_name text NOT NULL,
  display_name text, release_date date NOT NULL, eci numeric NOT NULL, ci_low numeric, ci_high numeric,
  organization text, source_url text, PRIMARY KEY (source, model_name));
INSERT INTO fct_autonomy_horizons (source, metric, model_name, release_date, value_hours, is_synthetic)
 VALUES ('METR','T50','gpt-4-0314','2023-03-14',0.0883,false);
