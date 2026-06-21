-- Add per-employee payroll proration toggle.
ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS prorate_payroll BOOLEAN NOT NULL DEFAULT TRUE;
