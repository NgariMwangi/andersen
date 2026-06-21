"""
Base model and mixins for SQLAlchemy models.
"""
from datetime import datetime
from app.extensions import db


class TimestampMixin:
    """Mixin for created_at and updated_at."""
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class BaseModel(db.Model):
    """Abstract base with id and timestamps."""
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self, exclude=None):
        """Convert to dict for JSON; exclude sensitive or heavy fields."""
        exclude = exclude or []
        return {
            c.name: getattr(self, c.name)
            for c in self.__table__.columns
            if c.name not in exclude
        }
