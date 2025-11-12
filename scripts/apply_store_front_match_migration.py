"""Apply the store front match DB migration.

This script connects to the application's configured database (via
`src.enterprise_config.config`) and runs the ALTER TABLE statements to add
`store_front_match_score` and `store_front_match` if they do not exist.

Usage (recommended):

  # ensure env vars are set, e.g. in zsh
  export DATABASE_URL="postgresql://postgres:your_password@localhost:5432/imageprocessing"
  python3 scripts/apply_store_front_match_migration.py

Or run with a one-off DATABASE_URL:

  DATABASE_URL="postgresql://postgres:pw@localhost:5432/dbname" python3 scripts/apply_store_front_match_migration.py

Note: This script requires the project's dependencies (SQLAlchemy, psycopg2)
to be installed in the environment (pip install -r requirements.txt).
"""
from sqlalchemy import create_engine, text
import sys
import traceback
import os

# Ensure repo root is on sys.path so imports like `src.enterprise_config` work
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    # Import local config
    from src.enterprise_config import config
except Exception:
    # Fallback if script run from repo root where package imports may differ
    try:
        from enterprise_config import config  # type: ignore
    except Exception:
        print("Failed to import application config from src.enterprise_config. Make sure to run this from the repo root and that dependencies are installed.")
        traceback.print_exc()
        sys.exit(1)


MIGRATION_SQL = """
BEGIN;

ALTER TABLE url_analysis_results
  ADD COLUMN IF NOT EXISTS store_front_match_score INTEGER;

ALTER TABLE url_analysis_results
  ADD COLUMN IF NOT EXISTS store_front_match VARCHAR(50);

COMMIT;
"""


def main():
    db_conf = config.get_database_config()
    db_url = db_conf.get('url') or db_conf.get('database_url')

    if not db_url:
        print("No database URL configured. Set the DATABASE_URL environment variable or configure the application settings.")
        sys.exit(1)

    print(f"Connecting to database: {db_url}")

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            print("Running migration SQL...")
            conn.execute(text(MIGRATION_SQL))
            print("Migration applied successfully.")
    except Exception as e:
        print("Failed to apply migration:", e)
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
