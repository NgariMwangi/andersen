-- Make employee number unique per branch (not company-wide).
-- Run once on existing PostgreSQL databases.

-- 1) Drop old company/global uniqueness created from employee_number UNIQUE.
ALTER TABLE employees DROP CONSTRAINT IF EXISTS employees_employee_number_key;
DROP INDEX IF EXISTS ix_employees_employee_number;

-- 2) Enforce uniqueness only within the same branch.
-- Partial index allows multiple NULL employee numbers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_branch_employee_number
ON employees (branch_id, employee_number)
WHERE employee_number IS NOT NULL;
