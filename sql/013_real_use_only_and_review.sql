-- =====================================================================
-- 013_real_use_only_and_review.sql
-- 1. На коло лідерів потрапляють ЛИШЕ дані реального використання
--    (method = 'internal_use_sample'). Перегенерація трафіку новою моделлю
--    ('deployment_simulation') - це прогін моделі на записаних запитах, тобто тест,
--    а не її реальна робота. Такі рядки лишаються в таблиці як історія, але
--    ні на коло, ні в чергу на перевірку більше не потрапляють.
-- 2. Рішення людини на сторінці перевірки (pages/review.py):
--      підтверджено: verified = true,  verified_by = 'human'
--      відхилено:    verified = false, verified_by = 'human', причина в notes
--    Збирач не перезаписує рядки з verified_by = 'human' (collectors/system_cards.py,
--    save) і не видаляє їх (_delete_pending видаляє лише verified_by IS NULL),
--    тож відхилений запис не з'явиться в черзі знову.
-- Ідемпотентно. Потрібні 005, 006, 007.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

CREATE OR REPLACE VIEW v_leader_action_models AS
WITH per_model AS (
    SELECT lab, model_name, max(release_date) AS release_date,
           avg(rate_out) AS rate_out,
           sum(n_total) AS n_total, sum(n_out) AS n_out,
           jsonb_agg(jsonb_build_object(
               'source_doc', source_doc, 'source_url', source_url, 'section', section, 'page', page,
               'method', method, 'unit', unit, 'classifier', classifier,
               'n_total', n_total, 'n_out', n_out, 'rate_out', rate_out,
               'counted', counted, 'excluded', excluded, 'data_origin', data_origin,
               'verified_by', verified_by)
             ORDER BY source_doc) AS sources
    FROM fct_leader_action_rates
    WHERE verified AND method = 'internal_use_sample'
    GROUP BY lab, model_name
), with_eci AS (
    SELECT p.*,
           (SELECT max(c.eci) FROM fct_capability_index c
             WHERE radar_model_match(p.model_name, c.model_name)
                OR radar_model_match(p.model_name, c.display_name)) AS eci
    FROM per_model p
), lab_top AS (                       -- найсильніша модель лабораторії за ECI, з даними чи без
    SELECT DISTINCT ON (organization) organization AS lab,
           coalesce(display_name, model_name) AS lab_top_model, eci AS lab_top_eci
    FROM fct_capability_index
    WHERE organization IS NOT NULL
    ORDER BY organization, eci DESC
), chosen AS (
    SELECT DISTINCT ON (lab) *,
           CASE WHEN eci IS NOT NULL THEN 'eci' ELSE 'newest' END AS leader_basis
    FROM with_eci
    ORDER BY lab, (eci IS NULL), eci DESC NULLS LAST, release_date DESC
)
SELECT c.lab, c.model_name, c.release_date, c.rate_out, c.n_total, c.n_out, c.sources,
       CASE WHEN jsonb_array_length(c.sources) = 1 THEN (radar_wilson(c.n_out, c.n_total)).lo END AS ci_low,
       CASE WHEN jsonb_array_length(c.sources) = 1 THEN (radar_wilson(c.n_out, c.n_total)).hi END AS ci_high,
       c.eci, c.leader_basis, t.lab_top_model, t.lab_top_eci
FROM chosen c
LEFT JOIN lab_top t ON lower(t.lab) = lower(c.lab)
ORDER BY c.lab;

-- Черга на перевірку: лише реальне використання, лише ще не вирішені людиною
CREATE OR REPLACE VIEW v_leader_action_pending AS
SELECT id, lab, model_name, release_date, section, page, method, rate_out, n_total, n_out,
       data_origin, notes, verification_log
FROM fct_leader_action_rates
WHERE NOT verified AND verified_by IS NULL AND method = 'internal_use_sample'
ORDER BY release_date DESC;

INSERT INTO ops_schema_migrations (version) VALUES ('013_real_use_only_and_review') ON CONFLICT DO NOTHING;
COMMIT;
