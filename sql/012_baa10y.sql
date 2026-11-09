-- =====================================================================
-- 012_baa10y.sql
-- Кредитний спред з довгою історією для перевірки індексу на корекції 2022 року.
-- Ряди ICE (fred_ig_oas, fred_hy_oas) FRED віддає лише за останні 3 роки.
-- BAA10Y = дохідність облігацій Moody's Baa мінус 10-річні облігації США, щоденно з 1986 року.
-- Значення пише collectors/fred_series.py.
-- =====================================================================
BEGIN;
INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('fred_baa10y', 'Спред облігацій Baa над 10-річними облігаціями США', 'Moody''s Baa yield minus 10-year Treasury', 'level',
   'FRED BAA10Y', NULL, 'percent', 'FRED: Moody''s Baa relative to DGS10 (BAA10Y)', 'daily', 'bubble',
   'Той самий сигнал «кредитори вимагають більшої премії», що й fred_ig_oas, але з повною історією - для перевірки індексу на 2022 році. Дані Moody''s: на публічному табло показувати похідний бал, а не сирий ряд.')
ON CONFLICT (metric_id) DO NOTHING;
INSERT INTO ops_schema_migrations (version) VALUES ('012_baa10y') ON CONFLICT DO NOTHING;
COMMIT;
