-- Run once on existing databases (create_all does not add columns to existing tables).
-- PostgreSQL:
ALTER TABLE employees ADD COLUMN IF NOT EXISTS contract_start_date DATE NULL;

-- SQLite 3 (no IF NOT EXISTS on older versions — skip if column already exists):
-- ALTER TABLE employees ADD COLUMN contract_start_date DATE NULL;
