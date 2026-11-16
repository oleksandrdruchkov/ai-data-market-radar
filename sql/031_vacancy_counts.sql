-- =====================================================================
-- 031_vacancy_counts.sql
-- Скільки активних вакансій стоїть за графіком навичок: регіон x джерело x напрям x рівень.
-- Сторінка показує це рядком під графіком навичок - зокрема скільки вакансій кожної китайської
-- лабораторії входить у регіон China (окремий графік вакансій китайських лабораторій прибрано).
-- Регіон вакансії визначає одна функція - і для навичок (v_skill_demand_stats), і для лічильника.
-- Ідемпотентно. Потрібна 030.
-- =====================================================================
BEGIN;

CREATE OR REPLACE FUNCTION radar_vacancy_region(p_region text, p_country_code text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_country_code = 'CN' OR p_region = 'China' THEN 'China'
        WHEN p_region IN ('EU', 'EMEA', 'Europe') THEN 'Europe'
        WHEN p_region IN ('US', 'USA') THEN 'US'
        WHEN p_region IN ('APAC', 'SG') THEN 'APAC'
        ELSE COALESCE(p_region, 'Global')
    END
$$;

CREATE OR REPLACE VIEW v_skill_demand_stats AS
SELECT
    radar_vacancy_region(v.region::text, v.country_code::text)::character varying AS region,
    s.canonical_name AS skill_name,
    s.category AS skill_category,
    v.track,
    v.experience_level,
    count(DISTINCT v.id) AS vacancy_count
FROM fct_vacancies v
JOIN bridge_vacancy_skills bvs ON v.id = bvs.vacancy_id
JOIN dim_skills s ON bvs.skill_id = s.skill_id
WHERE v.is_active = true
GROUP BY 1, s.canonical_name, s.category, v.track, v.experience_level;

DROP VIEW IF EXISTS v_vacancy_counts;
CREATE VIEW v_vacancy_counts AS
SELECT
    radar_vacancy_region(v.region::text, v.country_code::text) AS region,
    v.source,
    v.track,
    v.experience_level,
    count(*) AS vacancies,
    count(*) FILTER (WHERE EXISTS (SELECT 1 FROM bridge_vacancy_skills b WHERE b.vacancy_id = v.id)) AS with_skills
FROM fct_vacancies v
WHERE v.is_active = true
GROUP BY 1, v.source, v.track, v.experience_level;

GRANT SELECT ON v_vacancy_counts TO anon, authenticated;

INSERT INTO ops_schema_migrations (version) VALUES ('031_vacancy_counts') ON CONFLICT DO NOTHING;
COMMIT;
