"""Employee next-of-kin contacts and supervisor assignments."""
from app.extensions import db
from app.models.base import BaseModel


class EmployeeNextOfKin(BaseModel):
    """Next of kin / emergency contact for an employee (multiple allowed)."""
    __tablename__ = 'employee_next_of_kin'

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey('employees.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    full_name = db.Column(db.String(200), nullable=False)
    relationship = db.Column(db.String(80), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.Text, nullable=True)

    employee = db.relationship(
        'Employee',
        backref=db.backref(
            'next_of_kin',
            lazy='select',
            cascade='all, delete-orphan',
            order_by='EmployeeNextOfKin.id',
        ),
    )


class EmployeeSupervisor(BaseModel):
    """Many-to-many: employee may report to more than one supervisor."""
    __tablename__ = 'employee_supervisors'

    __table_args__ = (
        db.UniqueConstraint('employee_id', 'supervisor_id', name='uq_employee_supervisors_pair'),
    )

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey('employees.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    supervisor_id = db.Column(
        db.Integer,
        db.ForeignKey('employees.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    employee = db.relationship(
        'Employee',
        foreign_keys=[employee_id],
        backref=db.backref(
            'supervisor_links',
            lazy='select',
            cascade='all, delete-orphan',
            order_by='EmployeeSupervisor.id',
        ),
    )
    supervisor = db.relationship(
        'Employee',
        foreign_keys=[supervisor_id],
        lazy='joined',
    )
