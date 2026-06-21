"""Pytest fixtures for HRMS Kenya."""
import pytest
from app import create_app
from app.extensions import db
from config import TestingConfig


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app(TestingConfig)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def app_context(app):
    """Application context."""
    with app.app_context():
        yield


@pytest.fixture
def db_session(app, app_context):
    """Create tables and yield session; drop after test."""
    db.create_all()
    yield db.session
    db.session.remove()
    db.drop_all()
