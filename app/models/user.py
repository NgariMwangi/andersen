"""
User, roles and permissions for authentication and RBAC.
"""
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class Permission(db.Model):
    """Granular permission (e.g. view_employees, approve_leave)."""
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=True)


class Role(db.Model):
    """Role: ADMIN, HR_MANAGER, HR_STAFF, MANAGER, EMPLOYEE."""
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    permissions = db.relationship(
        'Permission',
        secondary='role_permissions',
        backref=db.backref('roles', lazy='dynamic'),
        lazy='select',
    )


class RolePermission(db.Model):
    """Many-to-many: Role <-> Permission."""
    __tablename__ = 'role_permissions'
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
    permission_id = db.Column(db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)


class User(UserMixin, db.Model):
    """User account linked to optional Employee; used for login and RBAC."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_superuser = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company_id = db.Column(db.Integer, db.ForeignKey('companies.id', ondelete='RESTRICT'), nullable=True)
    company = db.relationship('Company', backref=db.backref('users', lazy='dynamic'))

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)
    employee = db.relationship('Employee', backref=db.backref('user', uselist=False))

    roles = db.relationship(
        'Role',
        secondary='user_roles',
        backref=db.backref('users', lazy='dynamic'),
        lazy='select',
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_permission(self, permission_code):
        if self.is_superuser:
            return True
        for role in self.roles:
            for perm in role.permissions:
                if perm.code == permission_code:
                    return True
        return False

    def has_any_role(self, *codes):
        return any(r.code in codes for r in self.roles)

    @property
    def is_locked(self):
        if not self.locked_until:
            return False
        return datetime.utcnow() < self.locked_until


class UserRole(db.Model):
    """Many-to-many: User <-> Role."""
    __tablename__ = 'user_roles'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
