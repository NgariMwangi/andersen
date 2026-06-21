-- IT helpdesk tickets + permissions.
-- Run once on existing PostgreSQL databases.

CREATE TABLE IF NOT EXISTS ticket_categories (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ticket_categories_company_code UNIQUE (company_id, code)
);
CREATE INDEX IF NOT EXISTS ix_ticket_categories_company_id ON ticket_categories(company_id);

CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    ticket_number VARCHAR(30) NOT NULL,
    subject VARCHAR(300) NOT NULL,
    description TEXT NOT NULL,
    category_id INTEGER NULL REFERENCES ticket_categories(id) ON DELETE SET NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    requester_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    requester_employee_id INTEGER NULL REFERENCES employees(id) ON DELETE SET NULL,
    assigned_to_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    related_asset_id INTEGER NULL REFERENCES company_assets(id) ON DELETE SET NULL,
    resolved_at TIMESTAMP NULL,
    closed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tickets_company_number UNIQUE (company_id, ticket_number)
);
CREATE INDEX IF NOT EXISTS ix_tickets_company_id ON tickets(company_id);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS ticket_comments (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ticket_comments_ticket_id ON ticket_comments(ticket_id);

INSERT INTO permissions (code, name)
SELECT 'submit_tickets', 'Submit IT support tickets'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'submit_tickets');

INSERT INTO permissions (code, name)
SELECT 'view_tickets', 'View IT ticket queue'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'view_tickets');

INSERT INTO permissions (code, name)
SELECT 'manage_tickets', 'Manage IT tickets'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'manage_tickets');

INSERT INTO roles (code, name)
SELECT 'IT_SUPPORT', 'IT Support'
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE code = 'IT_SUPPORT');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'submit_tickets'
  AND r.code IN ('ADMIN', 'HR_MANAGER', 'HR_STAFF', 'MANAGER', 'EMPLOYEE', 'IT_SUPPORT')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'view_tickets'
  AND r.code IN ('ADMIN', 'IT_SUPPORT')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'manage_tickets'
  AND r.code IN ('ADMIN', 'IT_SUPPORT')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'send_messages'
  AND r.code = 'IT_SUPPORT'
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
