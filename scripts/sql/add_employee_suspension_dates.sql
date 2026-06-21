-- Suspension period dates for employee status workflow.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS suspension_from_date DATE NULL;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS suspension_to_date DATE NULL;
