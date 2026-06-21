"""Attendance tracking."""
from flask import Blueprint, render_template
from flask_login import login_required
from app.decorators.permissions import permission_required

attendance_bp = Blueprint('attendance', __name__)


@attendance_bp.route('/')
@login_required
@permission_required('view_attendance')
def index():
    return render_template('attendance/index.html')
