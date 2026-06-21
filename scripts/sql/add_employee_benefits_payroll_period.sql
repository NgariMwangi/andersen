-- Add payroll period columns for simple benefit posting.
ALTER TABLE employee_benefits
    ADD COLUMN IF NOT EXISTS payroll_year INTEGER NULL;

ALTER TABLE employee_benefits
    ADD COLUMN IF NOT EXISTS payroll_month INTEGER NULL;

-- Backfill from legacy effective_date where possible.
UPDATE employee_benefits
SET payroll_year = EXTRACT(YEAR FROM effective_date),
    payroll_month = EXTRACT(MONTH FROM effective_date)
WHERE effective_date IS NOT NULL
  AND (payroll_year IS NULL OR payroll_month IS NULL);
