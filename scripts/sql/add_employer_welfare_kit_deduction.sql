-- Add monthly welfare-kit deduction setting at employer level.
ALTER TABLE employers
    ADD COLUMN IF NOT EXISTS welfare_kit_deduction NUMERIC(14, 2) NOT NULL DEFAULT 0;
