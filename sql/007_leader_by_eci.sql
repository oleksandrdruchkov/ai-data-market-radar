-- =====================================================================
-- 007_leader_by_eci.sql
-- Лідер лабораторії для кола = модель з найвищим Epoch Capabilities Index (ECI)
-- серед моделей, для яких є підтверджені дані про дії. Якщо найсильніша модель
-- лабораторії даних не має, це видно в полях lab_top_model / lab_top_eci.
-- Якщо для лабораторії не знайдено жодного ECI - запасне правило: найновіша модель.
-- Ідемпотентно. Потрібні 004, 005, 006.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

-- 'Claude Mythos 5.1' -> {claude,mythos,5,1};  'claude-mythos-5-1_high' -> {claude,mythos,5,1,high}
CREATE OR REPLACE FUNCTION radar_model_tokens(name text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN btrim(regexp_replace(lower(coalesce(name, '')), '[^a-z0-9]+', ' ', 'g')) = '' THEN '{}'::text[]
                ELSE string_to_array(btrim(regexp_replace(lower(name), '[^a-z0-9]+', ' ', 'g')), ' ') END
$$;

-- Назва з картки збігається з назвою в Epoch, якщо її слова - початок назви Epoch,
-- а наступне слово не є номером версії (щоб 'Opus 5' не збігся з 'Opus 5.5').
CREATE OR REPLACE FUNCTION radar_model_match(card_name text, eci_name text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    WITH t AS (SELECT radar_model_tokens(card_name) a, radar_model_tokens(eci_name) b)
    SELECT cardinality(a) > 0
       AND cardinality(b) >= cardinality(a)
       AND b[1:cardinality(a)] = a
       AND (cardinality(b) = cardinality(a) OR b[cardinality(a) + 1] !~ '^[0-9]{1,2}$')
    FROM t
$$;

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
    WHERE verified
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

INSERT INTO ops_schema_migrations (version) VALUES ('007_leader_by_eci') ON CONFLICT DO NOTHING;
COMMIT;
