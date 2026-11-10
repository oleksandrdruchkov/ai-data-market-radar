-- 016: таблиці SEC отримують колонку external_id, як решта таблиць фактів.
-- Каркас записує факти через upsert з on_conflict = "external_id,source".
-- Безпечно запускати повторно.

begin;

alter table fct_lab_financials add column if not exists external_id text;
alter table fct_lab_filings    add column if not exists external_id text;

create unique index if not exists ux_lab_financials_ext on fct_lab_financials (external_id, source);
create unique index if not exists ux_lab_filings_ext    on fct_lab_filings    (external_id, source);

insert into ops_schema_migrations (version) values ('016_sec_external_id')
on conflict do nothing;

commit;
