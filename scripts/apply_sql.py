"""Apply a SQL file using DATABASE_URL from .env."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
url = os.environ.get("DATABASE_URL")
if not url:
    print("DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

import psycopg2

sql_path = Path(sys.argv[1])
sql = sql_path.read_text(encoding="utf-8")
conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql)
cur.close()
conn.close()
print(f"Applied {sql_path.name}")
