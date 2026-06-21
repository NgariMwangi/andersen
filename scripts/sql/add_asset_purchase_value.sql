-- Add optional purchase value to company assets (existing databases).
ALTER TABLE company_assets
ADD COLUMN IF NOT EXISTS purchase_value NUMERIC(14, 2) NULL;
