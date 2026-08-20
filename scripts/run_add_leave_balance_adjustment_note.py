"""One-off: add leave_balances.adjustment_note for HR deduction reasons."""
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
                ALTER TABLE leave_balances
                ADD COLUMN IF NOT EXISTS adjustment_note TEXT NULL
                """
            )
        )
        db.session.commit()
        print("OK: column leave_balances.adjustment_note added.")


if __name__ == "__main__":
    main()
