-- Add SHIF minimum monthly deduction amount for existing Kenya tenants.
-- Inserts SHIF_MIN_AMOUNT=300 for each company/effective_from where SHIF_PERCENT exists.

INSERT INTO statutory_rates (company_id, country_code, code, effective_from, value, description)
SELECT
    sr.company_id,
    sr.country_code,
    'SHIF_MIN_AMOUNT' AS code,
    sr.effective_from,
    300 AS value,
    'SHIF minimum monthly deduction amount' AS description
FROM statutory_rates sr
WHERE sr.country_code = 'KE'
  AND sr.code = 'SHIF_PERCENT'
  AND NOT EXISTS (
      SELECT 1
      FROM statutory_rates x
      WHERE x.company_id = sr.company_id
        AND x.country_code = sr.country_code
        AND x.effective_from = sr.effective_from
        AND x.code = 'SHIF_MIN_AMOUNT'
  );
