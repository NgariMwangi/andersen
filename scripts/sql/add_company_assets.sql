-- Company asset register tables + permissions.
-- Run once on existing PostgreSQL databases.

CREATE TABLE IF NOT EXISTS asset_categories (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_asset_categories_company_code UNIQUE (company_id, code)
);
CREATE INDEX IF NOT EXISTS ix_asset_categories_company_id ON asset_categories(company_id);

CREATE TABLE IF NOT EXISTS company_assets (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    category_id INTEGER NULL REFERENCES asset_categories(id) ON DELETE SET NULL,
    asset_tag VARCHAR(50) NOT NULL,
    name VARCHAR(200) NULL,
    brand VARCHAR(100) NULL,
    model VARCHAR(100) NULL,
    serial_number VARCHAR(100) NULL,
    description TEXT NULL,
    notes TEXT NULL,
    purchase_date DATE NULL,
    purchase_value NUMERIC(14, 2) NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'not_assigned',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_assets_company_tag UNIQUE (company_id, asset_tag)
);
CREATE INDEX IF NOT EXISTS ix_company_assets_company_id ON company_assets(company_id);
CREATE INDEX IF NOT EXISTS ix_company_assets_category_id ON company_assets(category_id);

CREATE TABLE IF NOT EXISTS asset_assignments (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES company_assets(id) ON DELETE CASCADE,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    assigned_at TIMESTAMP NOT NULL,
    returned_at TIMESTAMP NULL,
    condition_on_issue VARCHAR(200) NULL,
    condition_on_return VARCHAR(200) NULL,
    notes TEXT NULL,
    assigned_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    returned_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_asset_assignments_asset_id ON asset_assignments(asset_id);
CREATE INDEX IF NOT EXISTS ix_asset_assignments_employee_id ON asset_assignments(employee_id);

INSERT INTO permissions (code, name)
SELECT 'view_assets', 'View company assets'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'view_assets');

INSERT INTO permissions (code, name)
SELECT 'manage_assets', 'Manage company assets'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'manage_assets');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'view_assets'
  AND r.code IN ('ADMIN', 'HR_MANAGER', 'HR_STAFF', 'MANAGER')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'manage_assets'
  AND r.code IN ('ADMIN', 'HR_MANAGER', 'HR_STAFF')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
