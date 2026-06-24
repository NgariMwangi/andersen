-- Preserve original upload filename for display and download (existing databases).
ALTER TABLE employee_documents
ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255) NULL;

-- Best-effort backfill for documents uploaded before this column existed.
UPDATE employee_documents
SET original_filename = name
WHERE original_filename IS NULL AND name IS NOT NULL;
