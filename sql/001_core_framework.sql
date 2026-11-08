-- =====================================================================
-- 001_core_framework.sql
-- Перехід на спільний каркас збирачів. БЕЗПЕЧНО для наявних даних:
--   * нічого не видаляється і не перейменовується (крім значень source для Adzuna, див. §4);
--   * усі зміни ідемпотентні: файл можна запустити повторно;
--   * усе в одній транзакції: якщо щось не так, база лишається як була.
-- Запуск: Supabase -> SQL Editor -> вставити весь файл -> Run.
-- Перед запуском рекомендовано: Database -> Backups (або pg_dump).
-- =====================================================================

BEGIN;
SET LOCAL client_min_messages = warning;

-- ---------------------------------------------------------------------
-- 0. Журнал міграцій
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 1. Сирі дані: одна таблиця для всіх джерел. Ніколи не змінюється за змістом:
--    оновлюються лише last_seen_at і статус обробки.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_items (
    raw_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         text        NOT NULL,
    external_id    text        NOT NULL,
    content_hash   text        NOT NULL,
    payload        jsonb       NOT NULL,
    first_seen_at  timestamptz NOT NULL DEFAULT now(),
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    status         text        NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','processed','deferred','failed','legacy')),
    error          text,
    processed_at   timestamptz,
    CONSTRAINT ux_raw_items_source_hash UNIQUE (source, content_hash)
);
CREATE INDEX IF NOT EXISTS ix_raw_items_source_status ON raw_items (source, status);
CREATE INDEX IF NOT EXISTS ix_raw_items_source_ext    ON raw_items (source, external_id);

-- Атомарний «записати або позначити, що бачили знову».
-- first_seen_at і payload при повторі не змінюються.
CREATE OR REPLACE FUNCTION radar_touch_raw(
    p_source text, p_external_id text, p_content_hash text,
    p_payload jsonb, p_seen_at timestamptz DEFAULT now()
) RETURNS TABLE (raw_id bigint, is_new boolean)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    INSERT INTO raw_items AS r (source, external_id, content_hash, payload, first_seen_at, last_seen_at)
    VALUES (p_source, p_external_id, p_content_hash, p_payload, p_seen_at, p_seen_at)
    ON CONFLICT (source, content_hash)
    DO UPDATE SET last_seen_at = GREATEST(r.last_seen_at, EXCLUDED.last_seen_at)
    RETURNING r.raw_id, (xmax = 0) AS is_new;   -- xmax = 0 => рядок щойно вставлено
END $$;

-- ---------------------------------------------------------------------
-- 2. Журнал запусків, попередження якості, кеш LLM, реєстр джерел
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops_collector_runs (
    run_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source             text        NOT NULL,
    collector_version  text,
    status             text        NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running','ok','partial','failed')),
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    items_seen         int DEFAULT 0,
    items_new          int DEFAULT 0,
    items_updated      int DEFAULT 0,
    items_failed       int DEFAULT 0,
    items_deferred     int DEFAULT 0,
    items_closed       int DEFAULT 0,
    llm_calls          int DEFAULT 0,
    llm_fallbacks      int DEFAULT 0,
    llm_cache_hits     int DEFAULT 0,
    error              text
);
CREATE INDEX IF NOT EXISTS ix_runs_source_started ON ops_collector_runs (source, started_at DESC);

CREATE TABLE IF NOT EXISTS ops_quality_alerts (
    alert_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      bigint REFERENCES ops_collector_runs(run_id) ON DELETE SET NULL,
    source      text        NOT NULL,
    check_name  text        NOT NULL,
    severity    text        NOT NULL CHECK (severity IN ('info','warning','critical')),
    message     text        NOT NULL,
    value       numeric,
    threshold   numeric,
    created_at  timestamptz NOT NULL DEFAULT now(),
    acknowledged boolean    NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_alerts_created ON ops_quality_alerts (created_at DESC);

CREATE TABLE IF NOT EXISTS ops_llm_cache (
    prompt_name     text NOT NULL,
    prompt_version  text NOT NULL,
    content_hash    text NOT NULL,
    model           text NOT NULL,
    response        jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (prompt_name, prompt_version, content_hash)
);

-- Реєстр джерел: як часто кожне має оновлюватися. Основа для «джерело тихо замовкло».
CREATE TABLE IF NOT EXISTS ops_sources (
    source               text PRIMARY KEY,
    collector            text NOT NULL,
    fact_table           text,
    collection_method    text NOT NULL DEFAULT 'api'
                         CHECK (collection_method IN ('api','scrape','file','manual_seed')),
    expected_every_hours int  NOT NULL DEFAULT 24,
    is_enabled           boolean NOT NULL DEFAULT true,
    notes                text
);

INSERT INTO ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) VALUES
  ('adzuna',            'collectors/jobs_adzuna.py',   'fct_vacancies',        'api',         24, 'Перша сторінка пошуку, не повний ринок'),
  ('deepseek_careers',  'collectors/jobs_deepseek.py', 'fct_vacancies',        'manual_seed', 24, 'Живого джерела ще немає'),
  ('arxiv',             'collectors/arxiv.py',         'fct_arxiv_signals',    'api',         24, '5 найсвіжіших препринтів - вибірка, не повний потік'),
  ('epoch_metr',        'collector_horizons.py',       'fct_autonomy_horizons','file',        24, 'Ще не на новому каркасі')
ON CONFLICT (source) DO NOTHING;

-- ---------------------------------------------------------------------
-- 3. Спільні поля фактів. Допоміжна процедура додає їх до будь-якої fct_*.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION radar_add_fact_columns(p_table regclass) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format($f$
        ALTER TABLE %1$s
          ADD COLUMN IF NOT EXISTS source            text,
          ADD COLUMN IF NOT EXISTS source_url        text,
          ADD COLUMN IF NOT EXISTS event_date        date,
          ADD COLUMN IF NOT EXISTS first_seen_at     timestamptz,
          ADD COLUMN IF NOT EXISTS last_seen_at      timestamptz,
          ADD COLUMN IF NOT EXISTS region            text,
          ADD COLUMN IF NOT EXISTS collection_method text,
          ADD COLUMN IF NOT EXISTS extraction_method text,
          ADD COLUMN IF NOT EXISTS prompt_version    text,
          ADD COLUMN IF NOT EXISTS verified          boolean NOT NULL DEFAULT false,
          ADD COLUMN IF NOT EXISTS raw_item_id       bigint REFERENCES raw_items(raw_id) ON DELETE SET NULL,
          ADD COLUMN IF NOT EXISTS content_hash      text
    $f$, p_table);
END $$;

-- ---------------------------------------------------------------------
-- 4. fct_vacancies
-- ---------------------------------------------------------------------
DO $$ BEGIN PERFORM radar_add_fact_columns('fct_vacancies'); END $$;
ALTER TABLE fct_vacancies
    ADD COLUMN IF NOT EXISTS title_original      text,
    ADD COLUMN IF NOT EXISTS closed_at           timestamptz,
    ADD COLUMN IF NOT EXISTS salary_is_predicted boolean,
    ADD COLUMN IF NOT EXISTS work_model          text;

-- Нові збирачі не пишуть raw_job_id і можуть не знати posted_at: знімаємо NOT NULL, якщо був.
DO $$
DECLARE c text;
BEGIN
    FOREACH c IN ARRAY ARRAY['raw_job_id','posted_at'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'fct_vacancies'
                     AND column_name = c AND is_nullable = 'NO') THEN
            EXECUTE format('ALTER TABLE fct_vacancies ALTER COLUMN %I DROP NOT NULL', c);
        END IF;
    END LOOP;
END $$;

-- Adzuna: одне джерело замість adzuna_us / adzuna_gb, id Adzuna унікальний лише в межах країни.
UPDATE fct_vacancies
   SET external_id = substring(source from 8) || ':' || external_id,
       source      = 'adzuna'
 WHERE source LIKE 'adzuna\_%' AND external_id NOT LIKE '%:%';

-- Заповнення нових полів для старих рядків (лише там, де вони порожні)
-- created_at = коли рядок уперше потрапив у базу, тобто справжня «перша поява».
-- posted_at у DeepSeek перезаписувався кожним запуском, тож GREATEST дає «востаннє бачили».
UPDATE fct_vacancies SET
    first_seen_at     = COALESCE(first_seen_at, created_at, posted_at, now()),
    last_seen_at      = COALESCE(last_seen_at, GREATEST(created_at, posted_at), now()),
    -- справжня дата публікації відома лише з Adzuna; у DeepSeek posted_at був датою збору
    event_date        = COALESCE(event_date, CASE WHEN source = 'adzuna' THEN posted_at::date END),
    collection_method = COALESCE(collection_method, CASE WHEN source = 'deepseek_careers'
                                                         THEN 'manual_seed' ELSE 'api' END),
    extraction_method = COALESCE(extraction_method, 'legacy'),
    prompt_version    = COALESCE(prompt_version, 'legacy')
WHERE first_seen_at IS NULL OR extraction_method IS NULL;

ALTER TABLE fct_vacancies
    ALTER COLUMN first_seen_at SET DEFAULT now(),
    ALTER COLUMN last_seen_at  SET DEFAULT now();

-- bridge_vacancy_skills: первинний ключ (vacancy_id, skill_id) уже є - upsert працює без змін.

-- ---------------------------------------------------------------------
-- 5. fct_arxiv_signals
-- ---------------------------------------------------------------------
DO $$ BEGIN PERFORM radar_add_fact_columns('fct_arxiv_signals'); END $$;

UPDATE fct_arxiv_signals SET
    source            = COALESCE(source, 'arxiv'),
    source_url        = COALESCE(source_url, 'https://arxiv.org/abs/' || arxiv_id),
    event_date        = COALESCE(event_date, published_date::date),
    first_seen_at     = COALESCE(first_seen_at, created_at, now()),
    last_seen_at      = COALESCE(last_seen_at,  created_at, now()),
    collection_method = COALESCE(collection_method, 'api'),
    -- Старий аварійний фолбек писав саме ці значення: позначаємо їх, щоб не плутати з аналізом LLM
    extraction_method = COALESCE(extraction_method,
                          CASE WHEN predicted_skill = 'Frontier AI Systems'
                                AND predicted_role  = 'AI Systems Engineer'
                               THEN 'legacy_fallback' ELSE 'legacy' END),
    prompt_version    = COALESCE(prompt_version, 'legacy')
WHERE source IS NULL OR extraction_method IS NULL;

ALTER TABLE fct_arxiv_signals
    ALTER COLUMN source        SET DEFAULT 'arxiv',
    ALTER COLUMN first_seen_at SET DEFAULT now(),
    ALTER COLUMN last_seen_at  SET DEFAULT now();

-- ---------------------------------------------------------------------
-- 6. Перенесення історії raw_jobs -> raw_items (raw_jobs не чіпаємо)
-- ---------------------------------------------------------------------
INSERT INTO raw_items (source, external_id, content_hash, payload, first_seen_at, last_seen_at, status)
SELECT CASE WHEN rj.source LIKE 'adzuna\_%' THEN 'adzuna' ELSE rj.source END,
       CASE WHEN rj.source LIKE 'adzuna\_%' THEN substring(rj.source from 8) || ':' || rj.job_id
            ELSE rj.job_id END,
       rj.content_hash,
       COALESCE(rj.payload, '{}'::jsonb),
       COALESCE(rj.ingested_at, now()),
       COALESCE(rj.processed_at, rj.ingested_at, now()),
       'legacy'
FROM raw_jobs rj
ON CONFLICT (source, content_hash) DO NOTHING;

UPDATE fct_vacancies v
   SET raw_item_id = ri.raw_id
  FROM raw_items ri
 WHERE v.raw_item_id IS NULL
   AND ri.source = v.source
   AND ri.content_hash = v.content_hash;

-- ---------------------------------------------------------------------
-- 7. Реєстр показників і єдина таблиця значень
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_metrics (
    metric_id        text PRIMARY KEY,
    name_ua          text NOT NULL,
    name_en          text NOT NULL,
    description      text,
    kind             text NOT NULL CHECK (kind IN ('flow','stock','ratio','level')),
    numerator_def    text NOT NULL,
    denominator_def  text,
    unit             text NOT NULL,
    source           text NOT NULL,
    frequency        text NOT NULL CHECK (frequency IN ('daily','weekly','monthly','quarterly','irregular')),
    method_version   text NOT NULL DEFAULT 'v1',
    is_active        boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- «чесний знаменник»: частка без описаного знаменника не може існувати
    CONSTRAINT ck_ratio_has_denominator CHECK (kind <> 'ratio' OR denominator_def IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS fct_metric_values (
    metric_id       text NOT NULL REFERENCES dim_metrics(metric_id),
    period_start    date NOT NULL,
    period_end      date NOT NULL,
    region          text NOT NULL DEFAULT 'GLOBAL',
    value           numeric,
    lower_bound     numeric,
    upper_bound     numeric,
    numerator       numeric,
    denominator     numeric,
    is_estimate     boolean NOT NULL DEFAULT false,
    method_version  text NOT NULL DEFAULT 'v1',
    run_id          bigint REFERENCES ops_collector_runs(run_id) ON DELETE SET NULL,
    computed_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (metric_id, period_start, region),
    CONSTRAINT ck_period CHECK (period_end >= period_start),
    CONSTRAINT ck_bounds CHECK (lower_bound IS NULL OR upper_bound IS NULL OR lower_bound <= upper_bound)
);

INSERT INTO dim_metrics (metric_id, name_ua, name_en, kind, numerator_def, denominator_def, unit, source, frequency, description) VALUES
  ('vacancies_active', 'Активні вакансії', 'Active vacancies', 'stock',
   'count(fct_vacancies) where is_active', NULL, 'count', 'fct_vacancies', 'daily',
   'Запас на дату. Adzuna - лише перша сторінка пошуку, тому це вибірка, а не весь ринок.'),
  ('vacancies_new', 'Нові вакансії', 'New vacancies', 'flow',
   'count(fct_vacancies) by first_seen_at in period', NULL, 'count', 'fct_vacancies', 'daily', NULL),
  ('arxiv_signals_new', 'Нові сигнали ArXiv', 'New ArXiv signals', 'flow',
   'count(fct_arxiv_signals) by event_date in period', NULL, 'count', 'fct_arxiv_signals', 'daily', NULL),
  ('autonomy_t50_frontier', 'Горизонт автономності T50 моделі-лідера', 'Frontier T50 time horizon', 'level',
   'max(value_hours) where metric=T50 and release_date <= period_end', NULL, 'hours',
   'METR via Epoch AI (CC BY 4.0)', 'irregular', 'METR більше не оновлює вимірювання після 2026-09-08')
ON CONFLICT (metric_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 8. Представлення для табло (Streamlit читає тільки їх)
-- ---------------------------------------------------------------------

-- Стан кожного джерела: коли востаннє успішно працювало, чи не замовкло
CREATE OR REPLACE VIEW v_ops_source_freshness AS
WITH last_run AS (
    SELECT DISTINCT ON (source) source, run_id, status, started_at, items_seen, items_deferred, items_failed, error
    FROM ops_collector_runs ORDER BY source, started_at DESC
), last_ok AS (
    SELECT source, max(finished_at) AS last_ok_at
    FROM ops_collector_runs WHERE status IN ('ok','partial') GROUP BY source
)
SELECT s.source, s.collection_method, s.expected_every_hours, s.is_enabled,
       lr.status AS last_status, lr.started_at AS last_run_at,
       lr.items_seen, lr.items_deferred, lr.items_failed, lr.error AS last_error,
       lo.last_ok_at,
       round(extract(epoch FROM now() - lo.last_ok_at) / 3600.0, 1) AS hours_since_ok,
       CASE WHEN NOT s.is_enabled THEN 'disabled'
            WHEN lo.last_ok_at IS NULL THEN 'never_ok'
            WHEN now() - lo.last_ok_at > make_interval(hours => s.expected_every_hours * 2) THEN 'stale'
            WHEN lr.status = 'failed' THEN 'failing'
            ELSE 'fresh' END AS freshness
FROM ops_sources s
LEFT JOIN last_run lr ON lr.source = s.source
LEFT JOIN last_ok  lo ON lo.source = s.source;

-- Відкриті попередження за 14 днів
CREATE OR REPLACE VIEW v_ops_open_alerts AS
SELECT alert_id, source, check_name, severity, message, value, threshold, created_at
FROM ops_quality_alerts
WHERE NOT acknowledged AND created_at > now() - interval '14 days'
ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, created_at DESC;

-- Значення показників разом з їхнім описом: один формат для всіх графіків
CREATE OR REPLACE VIEW v_metric_series AS
SELECT v.metric_id, m.name_ua, m.name_en, m.kind, m.unit, m.source, m.numerator_def, m.denominator_def,
       v.period_start, v.period_end, v.region, v.value, v.lower_bound, v.upper_bound,
       v.numerator, v.denominator, v.is_estimate, v.method_version, v.computed_at
FROM fct_metric_values v JOIN dim_metrics m USING (metric_id)
WHERE m.is_active;

INSERT INTO ops_schema_migrations (version) VALUES ('001_core_framework')
ON CONFLICT (version) DO NOTHING;

COMMIT;
