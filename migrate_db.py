#!/usr/bin/env python3
"""
Simple database migration script to add listing data columns
"""
import os
import sys
from pathlib import Path

# Add the src directory to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def run_migration():
    """Run the database migration"""
    print("Running database migration for listing data columns...")

    try:
        # Import after adding to path
        from sqlalchemy import create_engine, text
        from dotenv import load_dotenv

        # Load environment variables
        load_dotenv()

        # Get database URL
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            # Fallback to individual vars
            host = os.getenv('POSTGRES_HOST', 'localhost')
            port = os.getenv('POSTGRES_PORT', '5432')
            db = os.getenv('POSTGRES_DB', 'image_analyzer')
            user = os.getenv('POSTGRES_USER', 'postgres')
            password = os.getenv('POSTGRES_PASSWORD', '')

            database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

        print(f"Connecting to database...")
        engine = create_engine(database_url)

        with engine.connect() as conn:
            # Define all the new listing data columns that need to be added
            new_columns = [
                ('serial_number', 'VARCHAR(100)'),
                ('business_name', 'VARCHAR(500)'),
                ('input_phone_number', 'VARCHAR(50)'),
                ('storefront_photo_url', 'TEXT'),
                ('phone_number', 'BOOLEAN'),
                # Phone match fields added by feature: phone_match_score (int) and phone_match (categorical)
                ('phone_match_score', 'INTEGER'),
                ('phone_match', 'VARCHAR(50)')
            ]

            print("Checking for missing columns...")

            # Check and add each missing column
            for column_name, column_type in new_columns:
                print(f"Checking column: {column_name}")

                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'url_analysis_results' 
                    AND column_name = :column_name
                """), {"column_name": column_name})

                if not result.fetchone():
                    print(f"Adding missing {column_name} column...")
                    conn.execute(text(f"""
                        ALTER TABLE url_analysis_results 
                        ADD COLUMN {column_name} {column_type}
                    """))
                    conn.commit()
                    print(f"✓ Added {column_name} column")
                else:
                    print(f"✓ {column_name} column already exists")

            # Add new indexes for performance
            indexes_to_create = [
                ('idx_serial_number', 'serial_number'),
                ('idx_business_name', 'business_name')
            ]

            print("Checking for missing indexes...")

            for index_name, column_name in indexes_to_create:
                try:
                    print(f"Checking index: {index_name}")

                    # Check if index exists
                    result = conn.execute(text("""
                        SELECT indexname 
                        FROM pg_indexes 
                        WHERE tablename = 'url_analysis_results' 
                        AND indexname = :index_name
                    """), {"index_name": index_name})

                    if not result.fetchone():
                        print(f"Creating index {index_name}...")
                        conn.execute(text(f"""
                            CREATE INDEX {index_name} ON url_analysis_results ({column_name})
                        """))
                        conn.commit()
                        print(f"✓ Created index {index_name}")
                    else:
                        print(f"✓ Index {index_name} already exists")
                except Exception as e:
                    print(f"Warning: Could not create index {index_name}: {e}")

        engine.dispose()
        print("\n🎉 Database migration completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
