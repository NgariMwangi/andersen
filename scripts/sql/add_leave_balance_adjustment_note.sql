-- HR leave deduction reason on leave_balances (PostgreSQL).
-- Run once, e.g.:
--   psql "$DATABASE_URL" -f scripts/sql/add_leave_balance_adjustment_note.sql

ALTER TABLE leave_balances
    ADD COLUMN IF NOT EXISTS adjustment_note TEXT;

COMMENT ON COLUMN leave_balances.adjustment_note IS 'HR reason when adjusted is negative (e.g. mid-year join deduction)';
