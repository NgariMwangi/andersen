-- PostgreSQL: add recurring vs one-off columns to public_holidays (fixes: column "kind" does not exist).
-- Run once, e.g.:
--   psql "postgresql://user:pass@host:5432/dbname" -f scripts/sql/postgres_migrate_public_holidays_kind.sql
--
-- Safe to re-run: only adds missing columns / constraints.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'public_holidays' AND column_name = 'kind'
  ) THEN
    ALTER TABLE public_holidays ADD COLUMN kind VARCHAR(20);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'public_holidays' AND column_name = 'recurring_month'
  ) THEN
    ALTER TABLE public_holidays ADD COLUMN recurring_month INTEGER NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'public_holidays' AND column_name = 'recurring_day'
  ) THEN
    ALTER TABLE public_holidays ADD COLUMN recurring_day INTEGER NULL;
  END IF;
END $$;

UPDATE public_holidays SET kind = 'one_off' WHERE kind IS NULL;

ALTER TABLE public_holidays ALTER COLUMN kind SET DEFAULT 'one_off';

-- Ensure no nulls before NOT NULL
UPDATE public_holidays SET kind = 'one_off' WHERE kind IS NULL;

ALTER TABLE public_holidays ALTER COLUMN kind SET NOT NULL;

-- Recurring holidays use date NULL
ALTER TABLE public_holidays ALTER COLUMN date DROP NOT NULL;

ALTER TABLE public_holidays DROP COLUMN IF EXISTS year;

CREATE INDEX IF NOT EXISTS ix_public_holidays_kind ON public_holidays (kind);
