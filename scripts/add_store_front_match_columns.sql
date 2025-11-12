-- Migration: add store_front_match_score and store_front_match to url_analysis_results
-- Run this against your PostgreSQL database used by the application.
-- Example:
-- psql $DATABASE_URL -f scripts/add_store_front_match_columns.sql
BEGIN;
ALTER TABLE url_analysis_results
ADD COLUMN IF NOT EXISTS store_front_match_score INTEGER;
ALTER TABLE url_analysis_results
ADD COLUMN IF NOT EXISTS store_front_match VARCHAR(50);
COMMIT;
-- Notes:
-- 1) Columns are nullable by design so existing rows are not affected.
-- 2) If you use Alembic or another migration tool, convert this SQL into a proper migration file.