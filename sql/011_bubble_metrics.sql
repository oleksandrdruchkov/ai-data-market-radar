-- =====================================================================
-- 011_bubble_metrics.sql
-- Перші показники «індексу крихкості» інвестиційної бульбашки ШІ.
-- Пишуться в загальну систему показників (dim_metrics / fct_metric_values),
-- поруч із показниками SAI, щоб обидва індекси жили на одній сторінці табло.
--
-- topic - до якого індексу належить показник:
--   sai     - автономність ШІ (SAI);
--   bubble  - індекс крихкості бульбашки;
--   shared  - «міст»: потрібен обом (вакансії, заміщення людей);
--   radar   - службові лічильники радара.
--
-- Джерела:
--   FRED (St. Louis Fed): ставки, кредитні спреди, індекси вакансій Indeed Hiring Lab;
--   Adzuna API: загальна кількість вакансій за запитом (поле count), а не самі оголошення.
-- Значення пишуть collectors/fred_series.py і collectors/adzuna_counts.py.
-- Жодних підставних значень: якщо джерело не відповіло, рядка немає.
-- =====================================================================
BEGIN;

ALTER TABLE dim_metrics ADD COLUMN IF NOT EXISTS topic text
    CHECK (topic IS NULL OR topic IN ('sai','bubble','shared','radar'));

UPDATE dim_metrics SET topic = 'sai'
 WHERE topic IS NULL AND metric_id IN ('autonomy_t50_frontier','sai_t_frontier');
UPDATE dim_metrics SET topic = 'radar'
 WHERE topic IS NULL AND metric_id IN ('vacancies_active','vacancies_new','arxiv_signals_new');

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  -- ---------- фінансування ----------
  ('fred_ig_oas', 'Кредитний спред інвестиційного рівня (США)', 'US investment-grade corporate OAS', 'level',
   'FRED BAMLC0A0CM', NULL, 'percent', 'FRED: ICE BofA US Corporate Index OAS (BAMLC0A0CM)', 'daily', 'bubble',
   'Замінник спредів гіперскейлерів (їхнього окремого кошика у вільному доступі немає). Розширення = кредитори вимагають більшої премії. Дані ICE мають обмеження на передрук: на публічному табло показувати похідний бал, а не сирий ряд.'),
  ('fred_hy_oas', 'Кредитний спред високодохідних облігацій (США)', 'US high-yield OAS', 'level',
   'FRED BAMLH0A0HYM2', NULL, 'percent', 'FRED: ICE BofA US High Yield Index OAS (BAMLH0A0HYM2)', 'daily', 'bubble',
   'Апетит до ризику загалом. Ті самі обмеження ICE на передрук, що й для fred_ig_oas.'),
  ('fred_ust10y', 'Дохідність 10-річних облігацій США', '10-year US Treasury yield', 'level',
   'FRED DGS10', NULL, 'percent', 'FRED: Board of Governors (DGS10)', 'daily', 'bubble',
   'Ціна довгих грошей: дорожчає - важче фінансувати багаторічні будівництва дата-центрів.'),
  ('fred_fed_funds', 'Ефективна ставка ФРС', 'Effective federal funds rate', 'level',
   'FRED DFF', NULL, 'percent', 'FRED: Federal Reserve Bank of New York (DFF)', 'daily', 'bubble',
   'Підвищення ставок передувало обвалам 2000 і 2008 років.'),
  -- ---------- люди (міст між індексами) ----------
  ('indeed_softdev_postings', 'Вакансії розробників на Indeed (індекс)', 'Software development job postings on Indeed', 'level',
   'FRED IHLIDX{CC}TPSOFTDEVE', NULL, 'index (2020-02-01 = 100)', 'FRED: Indeed Hiring Lab', 'daily', 'shared',
   'Звичайні вакансії розробників: US, GB, DE. Ковзне 7-денне, сезонно скориговане. Падіння разом з вакансіями ML = здування; падіння лише цього ряду при зростанні частки ШІ = заміщення.'),
  ('indeed_total_postings', 'Усі вакансії на Indeed (індекс)', 'All job postings on Indeed', 'level',
   'FRED IHLIDX{CC}', NULL, 'index (2020-02-01 = 100)', 'FRED: Indeed Hiring Lab', 'daily', 'shared',
   'Знаменник-орієнтир: чи падають вакансії розробників сильніше за ринок праці загалом.'),
  ('adzuna_ml_count', 'Кількість вакансій ML-інженерів (Adzuna)', 'Machine learning engineer postings (Adzuna count)', 'stock',
   'Adzuna search count, запит ml (див. method_version)', NULL, 'count', 'Adzuna API', 'daily', 'shared',
   'Загальна кількість результатів пошуку на дату, а не перша сторінка. Ті, хто будує ШІ.'),
  ('adzuna_swe_count', 'Кількість вакансій розробників (Adzuna)', 'Software developer postings (Adzuna count)', 'stock',
   'Adzuna search count, запит swe (див. method_version)', NULL, 'count', 'Adzuna API', 'daily', 'shared',
   'Загальна кількість результатів пошуку на дату. Звичайні розробники.'),
  ('adzuna_ml_share', 'Частка ML серед вакансій розробників (Adzuna)', 'ML share of developer postings (Adzuna)', 'ratio',
   'adzuna_ml_count', 'adzuna_swe_count', 'ratio', 'Adzuna API', 'daily', 'shared',
   'Відношення двох пошуків. Запити можуть перетинатися, тож це індикатор напрямку, а не точна частка.')
ON CONFLICT (metric_id) DO NOTHING;

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('fred_series',   'collectors/fred_series.py',   'fct_metric_values', 'api', 24,
   'FRED CSV без ключа; ринок не торгує у вихідні - нових точок у суботу/неділю немає'),
  ('adzuna_counts', 'collectors/adzuna_counts.py', 'fct_metric_values', 'api', 24,
   'Лише поле count пошуку, 2 запити x N ринків на день')
ON CONFLICT (source) DO NOTHING;

-- Представлення для табло: тепер із темою показника (нова колонка в кінці - CREATE OR REPLACE дозволяє)
CREATE OR REPLACE VIEW v_metric_series AS
SELECT v.metric_id, m.name_ua, m.name_en, m.kind, m.unit, m.source, m.numerator_def, m.denominator_def,
       v.period_start, v.period_end, v.region, v.value, v.lower_bound, v.upper_bound,
       v.numerator, v.denominator, v.is_estimate, v.method_version, v.computed_at, m.topic
FROM fct_metric_values v JOIN dim_metrics m USING (metric_id)
WHERE m.is_active;

INSERT INTO ops_schema_migrations (version) VALUES ('011_bubble_metrics') ON CONFLICT DO NOTHING;
COMMIT;
