-- =====================================================================
-- 028_indeed_ai_share_monthly.sql
-- Лінія «Фахівці ШІ» головного графіка - за всіма країнами Indeed AI Tracker, а не лише США.
-- Щоденний ряд indeed_ai_share (країна x день) зводиться до середнього за місяць, щоб сторінка
-- читала кілька сотень рядків, а не десятки тисяч. Розрахунок лінії - metrics/people.py.
-- Ідемпотентно. Потрібна 019.
-- =====================================================================
BEGIN;
SET LOCAL client_min_messages = warning;

DROP VIEW IF EXISTS v_indeed_ai_share_monthly;
CREATE VIEW v_indeed_ai_share_monthly AS
SELECT region,
       date_trunc('month', period_start)::date AS month,
       avg(value) AS value,
       count(*) AS n_days
FROM fct_metric_values
WHERE metric_id = 'indeed_ai_share' AND value IS NOT NULL
GROUP BY region, date_trunc('month', period_start)
ORDER BY region, month;

GRANT SELECT ON v_indeed_ai_share_monthly TO anon, authenticated;

INSERT INTO ops_schema_migrations (version) VALUES ('028_indeed_ai_share_monthly') ON CONFLICT DO NOTHING;
COMMIT;
