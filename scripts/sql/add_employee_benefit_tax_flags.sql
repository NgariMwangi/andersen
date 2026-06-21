-- Tax / pension flags for employee benefits (existing rows stay taxable & pensionable).
ALTER TABLE employee_benefits
    ADD COLUMN IF NOT EXISTS is_taxable BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE employee_benefits
    ADD COLUMN IF NOT EXISTS is_pensionable BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE employee_benefits
SET is_taxable = TRUE, is_pensionable = TRUE
WHERE is_taxable IS NULL OR is_pensionable IS NULL;
