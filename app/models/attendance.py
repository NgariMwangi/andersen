"""
Attendance / clock in-out records.
"""
from app.extensions import db
from app.models.base import BaseModel


class AttendanceRecord(BaseModel):
    """Single clock-in or clock-out (or both) for a day."""
    __tablename__ = 'attendance_records'
    __table_args__ = (
        db.Index('ix_attendance_records_employee_id', 'employee_id'),
        db.Index('ix_attendance_records_date', 'date'),
        db.Index('ix_attendance_records_employee_date', 'employee_id', 'date'),
    )

    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    clock_in = db.Column(db.Time, nullable=True)
    clock_out = db.Column(db.Time, nullable=True)
    break_minutes = db.Column(db.Integer, default=0, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(50), nullable=True)  # 'web', 'mobile', 'biometric'

    employee = db.relationship('Employee', backref='attendance_records')
