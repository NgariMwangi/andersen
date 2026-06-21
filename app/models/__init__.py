"""
SQLAlchemy models for HRMS Kenya.
Import all models here so they are registered with Flask-Migrate.
"""
from app.models.user import User, Role, Permission, UserRole
from app.models.company import Company, Branch
from app.models.employee import Employee
from app.models.employee_relations import EmployeeNextOfKin, EmployeeSupervisor
from app.models.employee_assignment_history import EmployeeAssignmentHistory
from app.models.department import Department
from app.models.job_title import JobTitle
from app.models.statutory import (
    StatutoryRateType,
    StatutoryRate,
    PayeBracket,
    NssfTier,
)
from app.models.audit import AuditLog
from app.models.payroll import (
    PayrollRun,
    PayrollItem,
    PayrollStatutoryRemittance,
    PayrollRunManualDeduction,
    PayrollRunExclusion,
    EmployeeSalary,
    EmployeeAllowance,
    Allowance,
    Deduction,
    EmployeeDeduction,
    EarningsDeductionType,
)
from app.models.leave import LeaveType, LeaveBalance, LeaveRequest, PublicHoliday
from app.models.overtime import OvertimeRequest
from app.models.attendance import AttendanceRecord
from app.models.document import EmployeeDocument, DocumentCategory
from app.models.notification import Notification
from app.models.report import SavedReport
from app.models.employer import Employer
from app.models.benefit import EmployeeBenefit, EmployeeBenefitPayment
from app.models.casual_worker import CasualWorker, CasualPayment
from app.models.consultant import (
    Consultant,
    ConsultantCompensation,
    ConsultantPayrollItem,
    ConsultantPayrollRunExclusion,
)
from app.models.message import Message, MessageRecipient, MessageThread, MessageThreadParticipant
from app.models.company_asset import AssetAssignment, AssetCategory, CompanyAsset
from app.models.it_ticket import Ticket, TicketCategory, TicketComment

__all__ = [
    'Company',
    'Branch',
    'User',
    'Role',
    'Permission',
    'UserRole',
    'Employee',
    'EmployeeNextOfKin',
    'EmployeeSupervisor',
    'EmployeeAssignmentHistory',
    'Department',
    'JobTitle',
    'StatutoryRateType',
    'StatutoryRate',
    'PayeBracket',
    'NssfTier',
    'AuditLog',
    'PayrollRun',
    'PayrollItem',
    'PayrollStatutoryRemittance',
    'PayrollRunManualDeduction',
    'PayrollRunExclusion',
    'Deduction',
    'EmployeeDeduction',
    'EmployeeSalary',
    'EmployeeAllowance',
    'Allowance',
    'EarningsDeductionType',
    'LeaveType',
    'LeaveBalance',
    'LeaveRequest',
    'PublicHoliday',
    'OvertimeRequest',
    'AttendanceRecord',
    'EmployeeDocument',
    'DocumentCategory',
    'Notification',
    'SavedReport',
    'Employer',
    'EmployeeBenefit',
    'EmployeeBenefitPayment',
    'CasualWorker',
    'CasualPayment',
    'Consultant',
    'ConsultantCompensation',
    'ConsultantPayrollItem',
    'ConsultantPayrollRunExclusion',
    'MessageThread',
    'MessageThreadParticipant',
    'Message',
    'MessageRecipient',
    'AssetCategory',
    'CompanyAsset',
    'AssetAssignment',
    'TicketCategory',
    'Ticket',
    'TicketComment',
]
