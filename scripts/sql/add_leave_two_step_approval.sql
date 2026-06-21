-- Two-step leave approval: supervisor fields + pending_hr status.
-- Run once on existing databases (create_all does not add columns to existing tables).

ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS supervisor_reviewed_by_id INTEGER NULL;
ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS supervisor_reviewed_at TIMESTAMP NULL;
ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS supervisor_notes TEXT NULL;
