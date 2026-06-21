-- Internal messaging tables + permissions.
-- Run once on existing PostgreSQL databases.

CREATE TABLE IF NOT EXISTS message_threads (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    subject VARCHAR(300) NOT NULL,
    thread_type VARCHAR(20) NOT NULL DEFAULT 'direct',
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_message_threads_company_id ON message_threads(company_id);

CREATE TABLE IF NOT EXISTS message_thread_participants (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES message_threads(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_message_thread_participants UNIQUE (thread_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_message_thread_participants_thread_id ON message_thread_participants(thread_id);
CREATE INDEX IF NOT EXISTS ix_message_thread_participants_user_id ON message_thread_participants(user_id);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES message_threads(id) ON DELETE CASCADE,
    parent_message_id INTEGER NULL REFERENCES messages(id) ON DELETE SET NULL,
    sender_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    send_email BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_messages_thread_id ON messages(thread_id);

CREATE TABLE IF NOT EXISTS message_recipients (
    id SERIAL PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at TIMESTAMP NULL,
    email_status VARCHAR(20) NULL,
    email_sent_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_message_recipients UNIQUE (message_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_message_recipients_message_id ON message_recipients(message_id);
CREATE INDEX IF NOT EXISTS ix_message_recipients_user_id ON message_recipients(user_id);

INSERT INTO permissions (code, name)
SELECT 'send_messages', 'Send internal messages'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'send_messages');

INSERT INTO permissions (code, name)
SELECT 'send_broadcast_messages', 'Message whole organization'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'send_broadcast_messages');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'send_messages'
  AND r.code IN ('ADMIN', 'HR_MANAGER', 'HR_STAFF', 'MANAGER', 'EMPLOYEE')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE p.code = 'send_broadcast_messages'
  AND r.code IN ('ADMIN', 'HR_MANAGER', 'HR_STAFF')
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
