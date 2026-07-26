-- RoofersParadise -- verify any number yourself. Run from the roofersparadise/ dir:
--   duckdb -c ".read queries.sql"
-- Every on-screen value resolves to a row here. No black box.

-- 1. Hail days in the last 90 days (cells + biggest stone per day)
select date, count(*) cells, round(max(hail_in),2) max_in
from read_parquet('data/hail/**/*.parquet')
where date >= strftime(current_date - 90, '%Y-%m-%d')
group by date order by date desc;

-- 2. Coverage by state (how much data we hold per state)
select state, count(*) cells, count(distinct date) hail_days
from read_parquet('data/hail/**/*.parquet')
group by state order by cells desc;

-- 3. Giant hail (2 inch+) events, most severe first
select date, state, round(max(hail_in),2) mx
from read_parquet('data/hail/**/*.parquet')
where hail_in >= 2 group by date, state order by mx desc limit 50;

-- 4. Provenance spot-check: where did a given date's data come from?
select distinct date, _source_file, _pipeline_run_id, _ingested_at
from read_parquet('data/hail/**/*.parquet')
where date = '2026-03-05';

-- 5. Florida-only recent hail (what the UI surfaces first)
select date, count(*) cells, round(max(hail_in),2) max_in
from read_parquet('data/hail/**/*.parquet')
where state = 'Florida' group by date order by date desc limit 30;
