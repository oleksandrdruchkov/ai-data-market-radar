-- =====================================================================
-- 025_arxiv_stop_resistance.sql
-- Окремий напрям у групі «Людський нагляд і надійність ШІ»: опір зупинці та втручанню
-- людини (ст. 14(4)(e) Регламенту ЄС про ШІ - втручання і зупинка кнопкою «стоп»).
-- Стрибок кількості статей - попередження signal_stop_resistance в ops_quality_alerts.
-- =====================================================================
BEGIN;
INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('arxiv_share_stop_resistance', 'Частка статей: опір зупинці та втручанню людини',
   'Share of papers: resistance to human interruption', 'ratio',
   'self-preservation, shutdown resistance/avoidance, resist modification, self-defense, self-protection, self-replication',
   'arxiv_papers_total', 'percent', 'arXiv API (totalResults)', 'monthly', 'shared',
   'Група «Людський нагляд і надійність ШІ», ст. 14(4)(e). Статей мало - дивитись на кількість (numerator) і попередження signal_stop_resistance.')
ON CONFLICT (metric_id) DO NOTHING;

ALTER TABLE ops_phrase_candidates DROP CONSTRAINT IF EXISTS ops_phrase_candidates_direction_check;
ALTER TABLE ops_phrase_candidates ADD CONSTRAINT ops_phrase_candidates_direction_check CHECK (
    direction IS NULL OR direction IN ('agents', 'self_improvement', 'robots', 'reasoning', 'ai_science',
                                       'oversight', 'understanding', 'robustness', 'undesired', 'risk',
                                       'stop_resistance'));

INSERT INTO ops_schema_migrations (version) VALUES ('025_arxiv_stop_resistance') ON CONFLICT DO NOTHING;
COMMIT;
