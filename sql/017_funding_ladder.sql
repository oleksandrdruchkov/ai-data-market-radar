-- =====================================================================
-- 017_funding_ladder.sql
-- Драбина фінансування перегонів ШІ (v0). Рахує metrics/funding_ladder.py
-- з даних SEC (fct_lab_financials, fct_lab_filings).
-- Сходинки: 0 власні кошти, 1 запаси, 2 борг, 3 кредит постачальника (Nvidia), 4 гроші населення.
-- Безпечно запускати повторно.
-- =====================================================================
BEGIN;

ALTER TABLE fct_lab_financials DROP CONSTRAINT IF EXISTS fct_lab_financials_metric_check;
ALTER TABLE fct_lab_financials ADD CONSTRAINT fct_lab_financials_metric_check CHECK (metric IN (
    'revenue', 'capex', 'rnd', 'net_income', 'cash',
    'ocf', 'debt_issued', 'equity_issued', 'buybacks', 'receivables', 'inventory'));

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('funding_ladder_rung', 'Драбина фінансування: найвища сходинка лабораторій-лідерів',
   'Funding ladder: highest rung among leading labs', 'level',
   'max(сходинка лабораторій) з урахуванням сигналу Nvidia', NULL, 'rung 0-4', 'metrics/funding_ladder.py',
   'monthly', 'bubble',
   'v0, пороги не перевірені. 0 власні кошти, 1 запаси, 2 борг, 3 кредит постачальника, 4 гроші населення. numerator = скільки лабораторій мали дані, denominator = скільки всього.'),
  ('funding_ladder_capex_ocf', 'Капвитрати / грошовий потік (найвище серед лабораторій)',
   'Capex / operating cash flow (highest among labs)', 'ratio',
   'капвитрати за 4 квартали', 'грошовий потік від основної діяльності за 4 квартали', 'ratio',
   'metrics/funding_ladder.py', 'monthly', 'bubble',
   'Більше 1 = будівництво вже не покривається власним заробітком. Дані всієї компанії, не лише ШІ.'),
  ('funding_ladder_vendor_gap', 'Nvidia: ріст дебіторки/запасів понад ріст виручки',
   'Nvidia: receivables/inventory growth over revenue growth', 'level',
   'max(ріст дебіторки, ріст запасів) - ріст виручки, рік до року', NULL, 'percentage points',
   'metrics/funding_ladder.py', 'monthly', 'bubble',
   'Понад 20 в.п. = сходинка 3: клієнти платять повільніше або попит слабшає.'),
  ('funding_ladder_rung_company', 'Драбина фінансування: сходинка компанії (службове)',
   'Funding ladder: company rung (internal)', 'level',
   'сходинка однієї компанії; region = тикер', NULL, 'rung 0-4', 'metrics/funding_ladder.py',
   'monthly', 'radar', 'Для перевірки розрахунку. На табло не виводиться.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('metrics_funding_ladder', 'metrics/funding_ladder.py', 'fct_metric_values', 'file', 24,
   'Розрахунок з уже зібраних даних SEC')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('017_funding_ladder') ON CONFLICT DO NOTHING;
COMMIT;
