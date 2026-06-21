-- Add column for working vs calendar day counting (PostgreSQL).
-- Run once, e.g.:
--   psql "$DATABASE_URL" -f scripts/sql/add_leave_types_days_count_basis.sql
-- Or from project root:
--   python scripts/run_add_days_count_basis.py

ALTER TABLE leave_types
    ADD COLUMN IF NOT EXISTS days_count_basis VARCHAR(20) NOT NULL DEFAULT 'working';

COMMENT ON COLUMN leave_types.days_count_basis IS 'working = Mon-Fri; calendar = consecutive calendar days (e.g. maternity)';

UPDATE leave_types SET days_count_basis = 'calendar' WHERE code = 'MATERNITY';
