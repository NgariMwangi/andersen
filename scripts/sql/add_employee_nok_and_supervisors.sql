-- Next of kin + multiple supervisors per employee.
-- Run once on existing databases (create_all does not add tables to existing DBs).

CREATE TABLE IF NOT EXISTS employee_next_of_kin (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    full_name VARCHAR(200) NOT NULL,
    relationship VARCHAR(80) NULL,
    phone VARCHAR(30) NULL,
    email VARCHAR(255) NULL,
    address TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_employee_next_of_kin_employee_id ON employee_next_of_kin(employee_id);

CREATE TABLE IF NOT EXISTS employee_supervisors (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    supervisor_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_employee_supervisors_pair UNIQUE (employee_id, supervisor_id)
);
CREATE INDEX IF NOT EXISTS ix_employee_supervisors_employee_id ON employee_supervisors(employee_id);
CREATE INDEX IF NOT EXISTS ix_employee_supervisors_supervisor_id ON employee_supervisors(supervisor_id);

-- Backfill single manager_id into supervisor links.
INSERT INTO employee_supervisors (employee_id, supervisor_id, created_at, updated_at)
SELECT e.id, e.manager_id, NOW(), NOW()
FROM employees e
WHERE e.manager_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM employee_supervisors es
      WHERE es.employee_id = e.id AND es.supervisor_id = e.manager_id
  );
