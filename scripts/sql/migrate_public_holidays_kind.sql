-- Upgrade public_holidays from (date, name, year) to recurring vs one-off.
-- Run once on existing databases. New installs get the full schema from SQLAlchemy create_all.
--
-- PostgreSQL: use scripts/sql/postgres_migrate_public_holidays_kind.sql (idempotent, drops NOT NULL on date, etc.).

-- SQLite / PostgreSQL compatible additions:
ALTER TABLE public_holidays ADD COLUMN kind VARCHAR(20);
UPDATE public_holidays SET kind = 'one_off' WHERE kind IS NULL;

ALTER TABLE public_holidays ADD COLUMN recurring_month INTEGER NULL;
ALTER TABLE public_holidays ADD COLUMN recurring_day INTEGER NULL;

-- Existing rows were all single calendar dates; keep as one-off. The old `year` column can be dropped manually if desired:
-- (SQLite 3.35+) ALTER TABLE public_holidays DROP COLUMN year;

-- If your SQLite build cannot add NULLable `date` for new recurring rows, recreate the table or use a fresh DB.
-- After migration, `date` may remain NOT NULL on old SQLite DBs — only one-off rows use `date`; recurring rows need date=NULL.
-- If INSERT recurring fails, export data, drop table, recreate with SQLAlchemy, re-import.
