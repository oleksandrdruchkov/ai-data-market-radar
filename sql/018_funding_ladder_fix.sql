-- =====================================================================
-- 018_funding_ladder_fix.sql
-- Виправлення драбини фінансування v0 після першого розрахунку:
--   * збирач SEC тепер бере дату ПЕРШОГО звіту з даними (раніше - звіт наступного року
--     з порівняльними даними, і розрахунок «на дату» бачив дані на рік пізніше);
--   * новий показник debt_repaid: сходинка 2 рахується з чистого боргу, без перекредитування;
--   * сигнал Nvidia - зміна відношення (дебіторка або запаси) / виручка, поріг 25 %.
-- Старі розрахунки видаляються; їх перерахує metrics/funding_ladder.py після backfill.
-- =====================================================================
BEGIN;

ALTER TABLE fct_lab_financials DROP CONSTRAINT IF EXISTS fct_lab_financials_metric_check;
ALTER TABLE fct_lab_financials ADD CONSTRAINT fct_lab_financials_metric_check CHECK (metric IN (
    'revenue', 'capex', 'rnd', 'net_income', 'cash',
    'ocf', 'debt_issued', 'debt_repaid', 'equity_issued', 'buybacks', 'receivables', 'inventory'));

UPDATE dim_metrics SET
    name_ua = 'Nvidia: зміна (дебіторка або запаси) / виручка за рік',
    name_en = 'Nvidia: year-over-year change of receivables or inventory relative to revenue',
    numerator_def = 'max зміни відношення дебіторка/виручка кварталу і запаси/виручка кварталу, рік до року',
    unit = 'percent',
    description = 'Понад 25 % = сходинка 3: клієнти платять повільніше або склад затоварюється.'
WHERE metric_id = 'funding_ladder_vendor_gap';

DELETE FROM fct_metric_values WHERE metric_id LIKE 'funding_ladder%';

INSERT INTO ops_schema_migrations (version) VALUES ('018_funding_ladder_fix') ON CONFLICT DO NOTHING;
COMMIT;
