"""One-off: add leave_types.days_count_basis for existing PostgreSQL DBs."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from sqlalchemy import text

from app import create_app
from app.extensions import db


def main():
    app = create_app()
    with app.app_context():
        db.session.execute(
            text(
                """
                ALTER TABLE leave_types
                ADD COLUMN IF NOT EXISTS days_count_basis VARCHAR(20) NOT NULL DEFAULT 'working'
                """
            )
        )
        db.session.execute(
            text(
                "UPDATE leave_types SET days_count_basis = 'calendar' WHERE code = 'MATERNITY'"
            )
        )
        db.session.commit()
        print("OK: column days_count_basis added; MATERNITY set to calendar.")


if __name__ == "__main__":
    main()
