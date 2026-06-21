"""API blueprint - internal REST endpoints."""
from flask import Blueprint

api_bp = Blueprint('api', __name__)

# Import and register API resources here
# from app.routes.api.employees_api import EmployeeListAPI
# api_bp.add_url_rule('/employees', view_func=EmployeeListAPI.as_view('employees'))
