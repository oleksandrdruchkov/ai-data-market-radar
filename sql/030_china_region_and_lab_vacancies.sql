-- =====================================================================
-- 030_china_region_and_lab_vacancies.sql
-- 1) Китай - окремий регіон у статистиці навичок (v_skill_demand_stats), а не частина APAC.
--    Вакансія китайська, якщо country_code = 'CN' або region = 'China'.
--    APAC - решта Азійсько-Тихоокеанського регіону (Сингапур, Індія ...).
-- 2) Джерела вакансій Moonshot, Zhipu, MiniMax (collectors/jobs_cn_labs.py);
--    розбір - ключовими словами, без мовної моделі (collectors/_job_keywords.py).
-- Ідемпотентно. Потрібна 001.
-- =====================================================================
BEGIN;

UPDATE fct_vacancies SET region = 'China' WHERE country_code = 'CN' AND region IS DISTINCT FROM 'China';

CREATE OR REPLACE VIEW v_skill_demand_stats AS
SELECT
    CASE
        WHEN v.country_code::text = 'CN' OR v.region::text = 'China' THEN 'China'::character varying
        WHEN v.region::text = ANY (ARRAY['EU', 'EMEA', 'Europe']) THEN 'Europe'::character varying
        WHEN v.region::text = ANY (ARRAY['US', 'USA']) THEN 'US'::character varying
        WHEN v.region::text = ANY (ARRAY['APAC', 'SG']) THEN 'APAC'::character varying
        ELSE COALESCE(v.region, 'Global'::character varying)
    END AS region,
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

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('moonshot_careers', 'collectors/jobs_cn_labs.py', 'fct_vacancies', 'scrape', 24,
   'Сторінка найму Moonshot (Kimi) на MokaHR; розбір ключовими словами, без моделі'),
  ('zhipu_careers', 'collectors/jobs_cn_labs.py', 'fct_vacancies', 'scrape', 24,
   'Сторінка найму Zhipu (Z.ai) на MokaHR; розбір ключовими словами, без моделі'),
  ('minimax_careers', 'collectors/jobs_cn_labs.py', 'fct_vacancies', 'scrape', 24,
   'Сторінка найму MiniMax на Feishu; розбір ключовими словами, без моделі')
ON CONFLICT (source) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('030_china_region_and_lab_vacancies') ON CONFLICT DO NOTHING;
COMMIT;
