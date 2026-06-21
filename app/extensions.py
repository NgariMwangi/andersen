"""
Centralized Flask extensions.
Initialized here, then init_app() called from app factory.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

# Database
db = SQLAlchemy()
migrate = Migrate()

# Auth
login_manager = LoginManager()

# Security
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per day", "500 per hour"])

# Mail
mail = Mail()
