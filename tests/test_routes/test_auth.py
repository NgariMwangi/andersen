"""Tests for auth routes."""
import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from config import TestingConfig


@pytest.fixture
def app():
    return create_app(TestingConfig)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_setup(app):
    with app.app_context():
        db.create_all()
        yield
        db.drop_all()


def test_login_page(client):
    r = client.get('/auth/login')
    assert r.status_code == 200
    assert b'Sign In' in r.data or b'login' in r.data.lower()


def test_login_post_invalid_returns_200(client, db_setup):
    """POST with invalid credentials should re-show login (no redirect)."""
    r = client.post('/auth/login', data={'email': 'nobody@example.com', 'password': 'wrong'}, follow_redirects=False)
    assert r.status_code == 200
