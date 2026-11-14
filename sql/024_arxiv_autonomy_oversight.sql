-- =====================================================================
-- 024_arxiv_autonomy_oversight.sql
-- Напрями ArXiv - у двох групах із назвами з Регламенту ЄС про ШІ (2024/1689):
--   autonomy  «Зростання автономності ШІ» (ознаки з визначення системи ШІ, ст. 3(1));
--   oversight «Людський нагляд і надійність ШІ» (ст. 14, 15) - колишній напрям safety,
--             розділений на п'ять напрямів.
-- arxiv_group_<група> - частка статей, що відповідають будь-якому напряму групи (один запит,
-- без повторного рахунку). Роботи тепер = робот + модель ШІ. Історія перераховується (версія v2).
-- =====================================================================
BEGIN;

UPDATE dim_metrics SET name_ua = 'Частка статей: автономне виконання завдань',
    name_en = 'Share of papers: autonomous task execution',
    description = 'Група «Зростання автономності ШІ». Агенти, що самі виконують багатокрокові завдання з інструментами.'
 WHERE metric_id = 'arxiv_share_agents';
UPDATE dim_metrics SET name_ua = 'Частка статей: адаптивність після розгортання',
    name_en = 'Share of papers: adaptiveness after deployment',
    description = 'Група «Зростання автономності ШІ». Модель покращує власні відповіді чи навчання (ст. 3(1): адаптивність після розгортання).'
 WHERE metric_id = 'arxiv_share_self_improvement';
UPDATE dim_metrics SET name_ua = 'Частка статей: вплив на фізичне середовище',
    name_en = 'Share of papers: influence on physical environments',
    description = 'Група «Зростання автономності ШІ». Лише роботи з моделлю ШІ (VLA, втілений ШІ, робот + мовна чи базова модель).'
 WHERE metric_id = 'arxiv_share_robots';
UPDATE dim_metrics SET name_ua = 'Частка статей: здатність до висновків',
    name_en = 'Share of papers: inference capability',
    description = 'Група «Зростання автономності ШІ». Модель довше й глибше думає над завданням.'
 WHERE metric_id = 'arxiv_share_reasoning';
UPDATE dim_metrics SET name_ua = 'Частка статей: автономні наукові дослідження',
    name_en = 'Share of papers: autonomous scientific research',
    description = 'Група «Зростання автономності ШІ». ШІ-науковець, автоматизовані відкриття.'
 WHERE metric_id = 'arxiv_share_ai_science';

UPDATE dim_metrics SET is_active = false,
    description = 'Замінено з 024: розділено на arxiv_share_oversight / understanding / robustness / undesired / risk.'
 WHERE metric_id = 'arxiv_share_safety';
DELETE FROM fct_metric_values WHERE metric_id = 'arxiv_share_safety';

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def,
                         unit, source, frequency, topic, description) VALUES
  ('arxiv_share_oversight', 'Частка статей: людський нагляд', 'Share of papers: human oversight', 'ratio',
   'фрази напряму oversight (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Група «Людський нагляд і надійність ШІ», ст. 14.'),
  ('arxiv_share_understanding', 'Частка статей: розуміння можливостей і обмежень ШІ', 'Share of papers: understanding AI capacities and limitations', 'ratio',
   'фрази напряму understanding (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Група «Людський нагляд і надійність ШІ», ст. 14(4)(a).'),
  ('arxiv_share_robustness', 'Частка статей: стійкість і кібербезпека', 'Share of papers: robustness and cybersecurity', 'ratio',
   'фрази напряму robustness (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Група «Людський нагляд і надійність ШІ», ст. 15.'),
  ('arxiv_share_undesired', 'Частка статей: виявлення небажаної поведінки', 'Share of papers: detecting undesirable behaviour', 'ratio',
   'фрази напряму undesired (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Група «Людський нагляд і надійність ШІ»: запобігання шкідливій або небажаній поведінці.'),
  ('arxiv_share_risk', 'Частка статей: запобігання ризикам для безпеки та прав людини', 'Share of papers: preventing risks to safety and rights', 'ratio',
   'фрази напряму risk (collectors/arxiv_counts.py)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Група «Людський нагляд і надійність ШІ», ст. 14(2).'),
  ('arxiv_group_autonomy', 'Частка статей: зростання автономності ШІ', 'Share of papers: growth of AI autonomy', 'ratio',
   'статті, що відповідають будь-якому напряму групи autonomy (один запит)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Висота стовпчика «Зростання автономності ШІ» без повторного рахунку статей.'),
  ('arxiv_group_oversight', 'Частка статей: людський нагляд і надійність ШІ', 'Share of papers: human oversight and robustness of AI', 'ratio',
   'статті, що відповідають будь-якому напряму групи oversight (один запит)', 'arxiv_papers_total', 'percent',
   'arXiv API (totalResults)', 'monthly', 'shared', 'Висота стовпчика «Людський нагляд і надійність ШІ» без повторного рахунку статей.')
ON CONFLICT (metric_id) DO NOTHING;

UPDATE ops_phrase_candidates SET direction = 'risk' WHERE direction = 'safety';
ALTER TABLE ops_phrase_candidates DROP CONSTRAINT IF EXISTS ops_phrase_candidates_direction_check;
ALTER TABLE ops_phrase_candidates ADD CONSTRAINT ops_phrase_candidates_direction_check CHECK (
    direction IS NULL OR direction IN ('agents', 'self_improvement', 'robots', 'reasoning', 'ai_science',
                                       'oversight', 'understanding', 'robustness', 'undesired', 'risk'));

INSERT INTO ops_schema_migrations (version) VALUES ('024_arxiv_autonomy_oversight') ON CONFLICT DO NOTHING;
COMMIT;
