-- Ensure frequency exists for employee benefits and defaults to one_off.
UPDATE employee_benefits
SET frequency = 'one_off'
WHERE frequency IS NULL OR trim(frequency) = '';

ALTER TABLE employee_benefits
    ALTER COLUMN frequency SET DEFAULT 'one_off';
