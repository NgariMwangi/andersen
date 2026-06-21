"""
Effective-dated assignment / role history (branch, department, job title, manager, status).
Complements Employee master row and salary history for a full career timeline.
"""
from app.extensions import db
from app.models.base import BaseModel


class EmployeeAssignmentHistory(BaseModel):
    """One segment of org/role assignment; open-ended when effective_to is null."""

    __tablename__ = 'employee_assignment_history'
    __table_args__ = (
        db.Index('ix_emp_assign_hist_employee', 'employee_id'),
        db.Index('ix_emp_assign_hist_effective_from', 'effective_from'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)

    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id', ondelete='SET NULL'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    job_title_id = db.Column(db.Integer, db.ForeignKey('job_titles.id', ondelete='SET NULL'), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True)

    status = db.Column(db.String(30), nullable=True)
    employment_type = db.Column(db.String(30), nullable=True)

    change_reason = db.Column(db.String(500), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    employee = db.relationship('Employee', foreign_keys=[employee_id], backref='assignment_history_segments')
    branch = db.relationship('Branch', foreign_keys=[branch_id])
    department = db.relationship('Department', foreign_keys=[department_id])
    job_title = db.relationship('JobTitle', foreign_keys=[job_title_id])
    manager = db.relationship('Employee', foreign_keys=[manager_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
