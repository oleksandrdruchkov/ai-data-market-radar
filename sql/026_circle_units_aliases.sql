-- =====================================================================
-- 026_circle_units_aliases.sql
-- Приводить коло лідерів у відповідність до вже прийнятих правил:
-- 1. Тести-провокації не на колі. Два записи Anthropic, підтверджені раніше як
--    «реальне використання», насправді є випробуваннями:
--      Claude Opus 5.5   - «evaluations run without safeguards» (спроби втекти з пісочниці);
--      Claude Mythos Preview - «(simulated) Production evaluation».
--    Відхилено рішенням користувача 2026-11-15 (verified = false, verified_by = 'human'),
--    тож збирач їх не перезапише і в чергу вони не повернуться.
--    Нові такі записи збирач більше не підтверджує сам (collectors/_card_verify.provocation_signs).
-- 2. Одна модель під різними назвами: Claude Mythos X і Claude Fable X - та сама модель
--    з різними захисними налаштуваннями. dim_model_aliases зводить їх до назви з ECI,
--    тож лідер лабораторії за ECI отримує свої дані.
-- 3. Частоти з різними одиницями рахунку (репліка, запуск, завдання...) не усереднюються:
--    модель рахується окремо за кожною одиницею, коло - теж окремо за одиницею.
-- Ідемпотентно. Потрібні 005-013.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

-- 1. Відхилити випробування, що потрапили на коло
UPDATE fct_leader_action_rates
   SET verified = false, verified_by = 'human', verified_at = now(),
       notes = 'Відхилено 2026-11-15: тест-провокація (випробування без захисту / симуляція), не реальна робота моделі.'
 WHERE lab = 'Anthropic'
   AND model_name IN ('Claude Opus 5.5', 'Claude Mythos Preview')
   AND verified;

-- 2. Синоніми назв моделей
CREATE TABLE IF NOT EXISTS dim_model_aliases (
    lab        text NOT NULL,
    alias      text NOT NULL,
    canonical  text NOT NULL,
    note       text,
    PRIMARY KEY (lab, alias)
);
ALTER TABLE dim_model_aliases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS dim_model_aliases_read ON dim_model_aliases;
CREATE POLICY dim_model_aliases_read ON dim_model_aliases FOR SELECT USING (true);

INSERT INTO dim_model_aliases (lab, alias, canonical, note) VALUES
    ('Anthropic', 'Claude Mythos 5',   'Claude Fable 5',   'та сама модель, інші захисні налаштування'),
    ('Anthropic', 'Claude Mythos 5.2', 'Claude Fable 5.2', 'та сама модель, інші захисні налаштування')
ON CONFLICT (lab, alias) DO UPDATE SET canonical = EXCLUDED.canonical, note = EXCLUDED.note;

-- 3. Представлення: модель x одиниця; коло - окремо за одиницею
DROP VIEW IF EXISTS v_leader_action_circle;
DROP VIEW IF EXISTS v_leader_action_models;

CREATE VIEW v_leader_action_models AS
WITH base AS (
    SELECT r.*, coalesce(a.canonical, r.model_name) AS model,
           CASE WHEN a.canonical IS NOT NULL THEN r.model_name END AS reported_as
    FROM fct_leader_action_rates r
    LEFT JOIN dim_model_aliases a ON a.lab = r.lab AND a.alias = r.model_name
    WHERE r.verified AND r.method = 'internal_use_sample'
), per_unit AS (
    SELECT lab, model, unit, max(release_date) AS release_date,
           avg(rate_out) AS rate_out,
           sum(n_total) AS n_total, sum(n_out) AS n_out,
           string_agg(DISTINCT reported_as, ', ') AS reported_as,
           jsonb_agg(jsonb_build_object(
               'model_name', model_name, 'source_doc', source_doc, 'source_url', source_url,
               'section', section, 'page', page, 'method', method, 'unit', unit,
               'classifier', classifier, 'n_total', n_total, 'n_out', n_out, 'rate_out', rate_out,
               'counted', counted, 'excluded', excluded, 'data_origin', data_origin,
               'verified_by', verified_by)
             ORDER BY source_doc) AS sources
    FROM base
    GROUP BY lab, model, unit
), models AS (
    SELECT lab, model, max(release_date) AS release_date,
           (SELECT max(c.eci) FROM fct_capability_index c
             WHERE radar_model_match(m.model, c.model_name)
                OR radar_model_match(m.model, c.display_name)) AS eci
    FROM (SELECT DISTINCT lab, model, release_date FROM per_unit) m
    GROUP BY lab, model
), lab_top AS (                       -- найсильніша модель лабораторії за ECI, з даними чи без
    SELECT DISTINCT ON (organization) organization AS lab,
           coalesce(display_name, model_name) AS lab_top_model, eci AS lab_top_eci
    FROM fct_capability_index
    WHERE organization IS NOT NULL
    ORDER BY organization, eci DESC
), chosen AS (                        -- лідер лабораторії: найвищий ECI, без ECI - найновіша
    SELECT DISTINCT ON (lab) lab, model, eci,
           CASE WHEN eci IS NOT NULL THEN 'eci' ELSE 'newest' END AS leader_basis
    FROM models
    ORDER BY lab, (eci IS NULL), eci DESC NULLS LAST, release_date DESC
)
SELECT p.lab, p.model AS model_name, p.unit, p.release_date, p.rate_out, p.n_total, p.n_out,
       p.reported_as, p.sources,
       CASE WHEN jsonb_array_length(p.sources) = 1 THEN (radar_wilson(p.n_out, p.n_total)).lo END AS ci_low,
       CASE WHEN jsonb_array_length(p.sources) = 1 THEN (radar_wilson(p.n_out, p.n_total)).hi END AS ci_high,
       c.eci, c.leader_basis, t.lab_top_model, t.lab_top_eci
FROM per_unit p
JOIN chosen c ON c.lab = p.lab AND c.model = p.model
LEFT JOIN lab_top t ON lower(t.lab) = lower(p.lab)
ORDER BY p.lab, p.unit;

-- Коло: одна одиниця - один рядок; на сторінці головне коло - одиниця з найбільшою кількістю лідерів
CREATE VIEW v_leader_action_circle AS
SELECT unit,
       count(*) AS n_models,
       avg(rate_out) AS out_share,
       (1)::numeric - avg(rate_out) AS in_share,
       min(rate_out) AS out_min,
       max(rate_out) AS out_max,
       max(release_date) AS latest_release,
       string_agg(lab || ': ' || model_name, ', ' ORDER BY lab) AS team
FROM v_leader_action_models
GROUP BY unit
ORDER BY count(*) DESC, max(release_date) DESC;

GRANT SELECT ON v_leader_action_models, v_leader_action_circle, dim_model_aliases TO anon, authenticated;

INSERT INTO ops_schema_migrations (version) VALUES ('026_circle_units_aliases') ON CONFLICT DO NOTHING;
COMMIT;
