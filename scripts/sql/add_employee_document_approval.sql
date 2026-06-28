-- Run once on existing databases (create_all does not add columns to existing tables).
ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) NOT NULL DEFAULT 'approved';
ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS uploaded_by_user_id INTEGER NULL;
ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS reviewed_by_user_id INTEGER NULL;
ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP NULL;
ALTER TABLE employee_documents ADD COLUMN IF NOT EXISTS review_notes TEXT NULL;

UPDATE employee_documents
SET approval_status = 'approved'
WHERE approval_status IS NULL OR approval_status = '';
