-- =====================================================================
-- 027_circle_periods.sql
-- Коло лідерів за періодами (місяцями), щоб на сторінці можна було вибрати попередній місяць.
--
-- Період = календарний місяць. Коло за минулий місяць - це ті самі підтверджені записи й ті самі
-- правила (sql/026), але лише за моделями, випущеними до кінця цього місяця:
--   * лідер лабораторії - найвищий ECI серед її моделей з даними, випущених до кінця місяця;
--   * «найсильніша модель лабораторії за ECI» - теж серед випущених до кінця місяця.
-- Тобто минулі місяці перераховано за сьогоднішніми правилами й сьогоднішніми підтвердженнями;
-- це не знімок того, що сторінка показувала тоді.
-- Останній період (поточний місяць) не має обмеження за датою - він дорівнює колу з sql/026.
-- Періоди - від місяця першого підтвердженого запису до поточного місяця.
--
-- v_leader_action_models і v_leader_action_circle тепер - останній період місячних представлень
-- (ті самі колонки й ті самі значення, що й у sql/026).
-- Ідемпотентно. Потрібні 005-013, 026.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

DROP VIEW IF EXISTS v_leader_action_circle;
DROP VIEW IF EXISTS v_leader_action_models;
DROP VIEW IF EXISTS v_leader_action_circle_monthly;
DROP VIEW IF EXISTS v_leader_action_models_monthly;

CREATE VIEW v_leader_action_models_monthly AS
WITH base AS (
    SELECT r.*, coalesce(a.canonical, r.model_name) AS model,
           CASE WHEN a.canonical IS NOT NULL THEN r.model_name END AS reported_as
    FROM fct_leader_action_rates r
    LEFT JOIN dim_model_aliases a ON a.lab = r.lab AND a.alias = r.model_name
    WHERE r.verified AND r.method = 'internal_use_sample'
), periods AS (
    SELECT g::date AS period,
           (g + interval '1 month' - interval '1 day')::date AS period_end,
           (g::date = date_trunc('month', current_date)::date) AS is_current
    FROM generate_series((SELECT least(date_trunc('month', min(release_date)), date_trunc('month', current_date)::timestamp) FROM base),
                         date_trunc('month', current_date)::timestamp,
                         interval '1 month') g
), per_unit AS (
    SELECT p.period, p.is_current, b.lab, b.model, b.unit, max(b.release_date) AS release_date,
           avg(b.rate_out) AS rate_out,
           sum(b.n_total) AS n_total, sum(b.n_out) AS n_out,
           string_agg(DISTINCT b.reported_as, ', ') AS reported_as,
           jsonb_agg(jsonb_build_object(
               'model_name', b.model_name, 'source_doc', b.source_doc, 'source_url', b.source_url,
               'section', b.section, 'page', b.page, 'method', b.method, 'unit', b.unit,
               'classifier', b.classifier, 'n_total', b.n_total, 'n_out', b.n_out, 'rate_out', b.rate_out,
               'counted', b.counted, 'excluded', b.excluded, 'data_origin', b.data_origin,
               'verified_by', b.verified_by)
             ORDER BY b.source_doc) AS sources
    FROM periods p
    JOIN base b ON p.is_current OR b.release_date <= p.period_end
    GROUP BY p.period, p.is_current, b.lab, b.model, b.unit
), models AS (
    SELECT period, lab, model, max(release_date) AS release_date,
           (SELECT max(c.eci) FROM fct_capability_index c
             WHERE radar_model_match(m.model, c.model_name)
                OR radar_model_match(m.model, c.display_name)) AS eci
    FROM (SELECT DISTINCT period, lab, model, release_date FROM per_unit) m
    GROUP BY period, lab, model
), lab_top AS (                       -- найсильніша модель лабораторії за ECI на кінець періоду
    SELECT DISTINCT ON (p.period, c.organization) p.period, c.organization AS lab,
           coalesce(c.display_name, c.model_name) AS lab_top_model, c.eci AS lab_top_eci
    FROM periods p
    JOIN fct_capability_index c ON p.is_current OR c.release_date <= p.period_end
    WHERE c.organization IS NOT NULL
    ORDER BY p.period, c.organization, c.eci DESC
), chosen AS (                        -- лідер лабораторії: найвищий ECI, без ECI - найновіша
    SELECT DISTINCT ON (period, lab) period, lab, model, eci,
           CASE WHEN eci IS NOT NULL THEN 'eci' ELSE 'newest' END AS leader_basis
    FROM models
    ORDER BY period, lab, (eci IS NULL), eci DESC NULLS LAST, release_date DESC
)
SELECT p.period, p.is_current,
       p.lab, p.model AS model_name, p.unit, p.release_date, p.rate_out, p.n_total, p.n_out,
       p.reported_as, p.sources,
       CASE WHEN jsonb_array_length(p.sources) = 1 THEN (radar_wilson(p.n_out, p.n_total)).lo END AS ci_low,
       CASE WHEN jsonb_array_length(p.sources) = 1 THEN (radar_wilson(p.n_out, p.n_total)).hi END AS ci_high,
       c.eci, c.leader_basis, t.lab_top_model, t.lab_top_eci
FROM per_unit p
JOIN chosen c ON c.period = p.period AND c.lab = p.lab AND c.model = p.model
LEFT JOIN lab_top t ON t.period = p.period AND lower(t.lab) = lower(p.lab)
ORDER BY p.period DESC, p.lab, p.unit;

-- Коло: період x одиниця рахунку; головне коло періоду - одиниця з найбільшою кількістю лідерів
CREATE VIEW v_leader_action_circle_monthly AS
SELECT period, is_current, unit,
       count(*) AS n_models,
       avg(rate_out) AS out_share,
       (1)::numeric - avg(rate_out) AS in_share,
       min(rate_out) AS out_min,
       max(rate_out) AS out_max,
       max(release_date) AS latest_release,
       string_agg(lab || ': ' || model_name, ', ' ORDER BY lab) AS team
FROM v_leader_action_models_monthly
GROUP BY period, is_current, unit
ORDER BY period DESC, count(*) DESC, max(release_date) DESC;

-- Поточний стан = останній період (колонки й значення - як у sql/026)
CREATE VIEW v_leader_action_models AS
SELECT lab, model_name, unit, release_date, rate_out, n_total, n_out, reported_as, sources,
       ci_low, ci_high, eci, leader_basis, lab_top_model, lab_top_eci
FROM v_leader_action_models_monthly
WHERE is_current
ORDER BY lab, unit;

CREATE VIEW v_leader_action_circle AS
SELECT unit, n_models, out_share, in_share, out_min, out_max, latest_release, team
FROM v_leader_action_circle_monthly
WHERE is_current
ORDER BY n_models DESC, latest_release DESC;

GRANT SELECT ON v_leader_action_models, v_leader_action_circle,
                v_leader_action_models_monthly, v_leader_action_circle_monthly TO anon, authenticated;

INSERT INTO ops_schema_migrations (version) VALUES ('027_circle_periods') ON CONFLICT DO NOTHING;
COMMIT;
