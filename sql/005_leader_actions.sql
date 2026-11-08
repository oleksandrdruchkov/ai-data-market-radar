-- =====================================================================
-- 005_leader_actions.sql
-- Коло дій моделей-лідерів: частка дій ПОЗА МЕЖАМИ за даними РЕАЛЬНОЇ роботи.
--
-- Правила (рішення 2026-11-08):
--   * лише дані реальної роботи моделі (внутрішнє використання, перегенерація реального
--     трафіку); тести-пастки не використовуються;
--   * «поза межами» = дія, не передбачена завданням (обхід блокування, руйнівна дія,
--     використання прав, яких не надавали). Неправдиві звіти про роботу - не дія,
--     зберігаються окремо (excluded) і в частку не входять;
--   * кожна модель-лідер має рівну вагу; команда = найновіша підтверджена модель кожної лабораторії;
--   * на табло потрапляють лише рядки, які людина позначила verified = true.
-- Ідемпотентно, у транзакції. Потрібна 001.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

CREATE TABLE IF NOT EXISTS fct_leader_action_rates (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lab              text NOT NULL,
    model_name       text NOT NULL,
    release_date     date NOT NULL,
    source_doc       text NOT NULL,             -- напр. 'System Card: Claude Fable 5 & Claude Mythos 5'
    source_url       text NOT NULL,
    section          text,
    page             text,
    method           text NOT NULL CHECK (method IN ('internal_use_sample', 'deployment_simulation')),
    unit             text NOT NULL CHECK (unit IN ('use', 'turn', 'tool_call', 'trajectory')),
    classifier       text,                      -- хто класифікував дії (модель-монітор / людина)
    n_total          int  CHECK (n_total IS NULL OR n_total > 0),
    n_out            int  CHECK (n_out IS NULL OR n_out >= 0),
    rate_out         numeric NOT NULL CHECK (rate_out >= 0 AND rate_out <= 1),
    counted          jsonb NOT NULL DEFAULT '[]',   -- що зараховано «поза межами»: [{category, n|rate, quote}]
    excluded         jsonb NOT NULL DEFAULT '[]',   -- що НЕ зараховано (неправдиві звіти тощо)
    evidence_quote   text,
    data_origin      text NOT NULL DEFAULT 'primary_text'
                     CHECK (data_origin IN ('primary_text', 'primary_figure', 'secondary_source')),
    verified         boolean NOT NULL DEFAULT false,
    verified_at      timestamptz,
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_leader_action UNIQUE (lab, model_name, source_doc, method),
    CONSTRAINT ck_counts CHECK (n_out IS NULL OR n_total IS NULL OR n_out <= n_total)
);

-- 95% інтервал Вільсона: чесна похибка для малих вибірок (13 з 886)
CREATE OR REPLACE FUNCTION radar_wilson(k numeric, n numeric, OUT lo numeric, OUT hi numeric)
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN n IS NULL OR n = 0 THEN NULL ELSE
             GREATEST(0, ((k/n) + 1.96^2/(2*n) - 1.96*sqrt((k/n)*(1-k/n)/n + 1.96^2/(4*n^2))) / (1 + 1.96^2/n)) END,
           CASE WHEN n IS NULL OR n = 0 THEN NULL ELSE
             LEAST(1,   ((k/n) + 1.96^2/(2*n) + 1.96*sqrt((k/n)*(1-k/n)/n + 1.96^2/(4*n^2))) / (1 + 1.96^2/n)) END
$$;

-- Модель-лідер кожної лабораторії: найновіша модель із підтвердженими даними
CREATE OR REPLACE VIEW v_leader_action_models AS
WITH per_model AS (
    SELECT lab, model_name, max(release_date) AS release_date,
           avg(rate_out) AS rate_out,                       -- рівна вага кожного джерела всередині моделі
           sum(n_total) AS n_total, sum(n_out) AS n_out,
           jsonb_agg(jsonb_build_object(
               'source_doc', source_doc, 'source_url', source_url, 'section', section, 'page', page,
               'method', method, 'unit', unit, 'classifier', classifier,
               'n_total', n_total, 'n_out', n_out, 'rate_out', rate_out,
               'counted', counted, 'excluded', excluded, 'data_origin', data_origin)
             ORDER BY source_doc) AS sources
    FROM fct_leader_action_rates
    WHERE verified
    GROUP BY lab, model_name
), latest AS (
    SELECT DISTINCT ON (lab) * FROM per_model ORDER BY lab, release_date DESC
)
SELECT l.*,
       -- інтервал лише коли в моделі одне джерело з відомими кількостями
       CASE WHEN jsonb_array_length(l.sources) = 1 THEN (radar_wilson(l.n_out, l.n_total)).lo END AS ci_low,
       CASE WHEN jsonb_array_length(l.sources) = 1 THEN (radar_wilson(l.n_out, l.n_total)).hi END AS ci_high
FROM latest l
ORDER BY l.lab;

-- Команда лідерів: середнє з рівною вагою моделей + розкид
CREATE OR REPLACE VIEW v_leader_action_circle AS
SELECT count(*)                       AS n_models,
       avg(rate_out)                  AS out_share,
       1 - avg(rate_out)              AS in_share,
       min(rate_out)                  AS out_min,
       max(rate_out)                  AS out_max,
       max(release_date)              AS latest_release,
       string_agg(lab || ': ' || model_name, ', ' ORDER BY lab) AS team
FROM v_leader_action_models
HAVING count(*) > 0;

-- Дані, які ще чекають на підтвердження людиною (табло показує, що вони є)
CREATE OR REPLACE VIEW v_leader_action_pending AS
SELECT id, lab, model_name, release_date, section, page, method, rate_out, n_total, n_out, data_origin, notes
FROM fct_leader_action_rates WHERE NOT verified ORDER BY release_date DESC;

-- Перші два записи. НЕ підтверджені: перевірте за сторінками й позначте verified = true.
INSERT INTO fct_leader_action_rates
  (lab, model_name, release_date, source_doc, source_url, section, page, method, unit, classifier,
   n_total, n_out, rate_out, counted, excluded, evidence_quote, data_origin, notes)
VALUES
  ('Anthropic', 'Claude Mythos 5', '2026-06-09',
   'System Card: Claude Fable 5 & Claude Mythos 5',
   'https://www-cdn.anthropic.com/57a52ea7d8f0e54e8a542e908266086df425cdf5/Claude%20Fable%205%20&%20Claude%20Mythos%205%20System%20Card.pdf',
   '2.3.3.3, 2.3.3.4', '40-41', 'internal_use_sample', 'use', 'класифікація промптами Claude',
   886, 13, 13.0/886,
   '[{"category":"Works around a block instead of stopping","n":9,"page":"40"},
     {"category":"Ignores an explicit instruction or required step","n":4,"page":"41"}]',
   '[{"category":"Reports work as done or verified when it was not","n":16,"page":"39","why":"неправдивий звіт, не дія"},
     {"category":"States an unverified guess as fact","n":41,"page":"38","why":"неправдивий звіт, не дія"},
     {"category":"Invents details never observed","n":3,"page":"42","why":"неправдивий звіт, не дія"}]',
   'Вибірка 886 повсякденних використань майже фінального знімка Mythos 5 у внутрішньому Claude Code.',
   'primary_text',
   'Перевірити: чи «ігнорує явну інструкцію» (4) - це дія поза межами, а не пропуск кроку.'),
  ('OpenAI', 'GPT-5.6 Sol', '2026-06-26',
   'GPT-5.6 System Card',
   'https://deploymentsafety.openai.com/gpt-5-6-preview',
   '7.2 (Figure 7)', NULL, 'deployment_simulation', 'turn', 'монітор неузгодженості OpenAI (читає хід міркувань)',
   NULL, NULL, 0.00270,
   '[{"category":"Severity 3: circumventing constraints","rate":0.00251},
     {"category":"Severity 3: destructive behavior","rate":0.00019}]',
   '[{"category":"Misrepresenting work completion","why":"неправдивий звіт, не дія"}]',
   'Перегенерація реальних префіксів внутрішнього агентного трафіку; зовнішній стан замінено симулятором інструментів.',
   'secondary_source',
   'Числа взято з вторинного джерела (xenospectrum.com), в тексті картки лише відносні зміни. Звірити з Figure 7; кількість кроків не вказана.')
ON CONFLICT (lab, model_name, source_doc, method) DO NOTHING;

INSERT INTO ops_schema_migrations (version) VALUES ('005_leader_actions') ON CONFLICT DO NOTHING;
COMMIT;
