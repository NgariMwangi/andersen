-- Colleague who covers duties while the requester is on leave.
-- Run once on existing databases (create_all does not add columns to existing tables).

ALTER TABLE leave_requests ADD COLUMN handover_to_id INTEGER NULL;

CREATE INDEX IF NOT EXISTS ix_leave_requests_handover_to_id ON leave_requests (handover_to_id);
