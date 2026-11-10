-- 015: ринкові сигнали учасників перегонів (SEC EDGAR)
-- Безпечно запускати повторно.

begin;

create table if not exists fct_lab_financials (
    id                bigserial primary key,
    ticker            text        not null,
    company_label     text        not null,
    role              text        not null check (role in ('lab', 'backer', 'supplier')),
    metric            text        not null check (metric in ('revenue', 'capex', 'rnd', 'net_income', 'cash')),
    period_type       text        not null check (period_type in ('quarter', 'year', 'instant')),
    period_start      date,
    period_end        date        not null,
    value             numeric     not null,
    currency          text        not null default 'USD',
    derived_from_ytd  boolean     not null default false,  -- квартал = різниця накопичувальних сум
    xbrl_concept      text        not null,
    form              text        not null,
    accession_no      text        not null,
    filed_date        date        not null,
    source_url        text        not null,
    unique (ticker, metric, period_type, period_end)
);
select radar_add_fact_columns('fct_lab_financials');

create table if not exists fct_lab_filings (
    id             bigserial primary key,
    ticker         text    not null,
    company_label  text    not null,
    role           text    not null check (role in ('lab', 'backer', 'supplier')),
    form           text    not null,
    category       text    not null,
    accession_no   text    not null,
    filed_date     date    not null,
    report_date    date,
    items          text[]  not null default '{}',
    items_labels   text[]  not null default '{}',
    description    text,
    source_url     text    not null,
    unique (ticker, accession_no)
);
select radar_add_fact_columns('fct_lab_filings');

-- Як інші нові таблиці: RLS увімкнено, політик немає -> доступ лише з service_role
alter table fct_lab_financials enable row level security;
alter table fct_lab_filings    enable row level security;

create index if not exists ix_lab_filings_date on fct_lab_filings (filed_date desc);
create index if not exists ix_lab_filings_items on fct_lab_filings using gin (items);

-- Квартали, вирівняні за календарем: фінансові роки різняться (Microsoft - червень,
-- Nvidia - кінець січня), тому квартал визначається за серединою періоду.
create or replace view v_lab_financials_quarterly with (security_invoker = true) as
select
    ticker,
    company_label,
    role,
    date_trunc('quarter', period_start + (period_end - period_start) / 2)::date as cal_quarter,
    currency,
    max(value) filter (where metric = 'revenue')    as revenue,
    max(value) filter (where metric = 'capex')      as capex,
    max(value) filter (where metric = 'rnd')        as rnd,
    max(value) filter (where metric = 'net_income') as net_income,
    bool_or(derived_from_ytd)                       as has_derived
from fct_lab_financials
where period_type = 'quarter'
group by 1, 2, 3, 4, 5;

-- «Паливо перегонів»: сумарні капітальні витрати лабораторій-лідерів і їхніх спонсорів, лише USD.
-- Увага: це витрати всієї компанії (у т.ч. не-ШІ), тобто верхня межа, а не точна сума на ШІ.
create or replace view v_race_fuel_quarterly with (security_invoker = true) as
select
    cal_quarter,
    sum(capex) filter (where role = 'lab')    as capex_labs_usd,
    sum(capex) filter (where role = 'backer') as capex_backers_usd,
    max(revenue) filter (where ticker = 'NVDA') as nvidia_revenue_usd,
    count(distinct ticker) filter (where capex is not null) as companies_reporting
from v_lab_financials_quarterly
where currency = 'USD'
group by cal_quarter
order by cal_quarter;

-- Події, які варто показувати на шкалі часу радара
create or replace view v_lab_key_filings with (security_invoker = true) as
select ticker, company_label, filed_date, form, category, items, items_labels, source_url
from fct_lab_filings
where category in ('ipo', 'ipo_pricing', 'follow_on', 'ownership', 'governance')
   or (form = '8-K' and items && array['1.05', '5.01', '5.02', '1.01', '2.03'])
order by filed_date desc;

insert into ops_sources (source, collector, fact_table, collection_method, expected_every_hours, notes) values
  ('sec_financials', 'collectors/sec_financials.py', 'fct_lab_financials', 'api', 24,
   'SEC XBRL companyfacts: виручка, капвитрати, R&D, прибуток; консолідовано по компанії, не лише ШІ'),
  ('sec_filings', 'collectors/sec_filings.py', 'fct_lab_filings', 'api', 24,
   'SEC submissions: IPO, розміщення, 8-K, 13D/G, Форма 4')
on conflict (source) do nothing;

insert into ops_schema_migrations (version) values ('015_market_signals')
on conflict do nothing;

commit;
