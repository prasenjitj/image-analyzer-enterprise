#!/usr/bin/env python3
"""
Enterprise setup script for image processing system

This script helps set up the enterprise infrastructure including:
- Database initialization
- Redis configuration
- Dependency installation
- Environment validation
"""
from sqlalchemy import create_engine, text
import os
import sys
import subprocess
import logging
from pathlib import Path
import asyncio
import time

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import sqlalchemy for database operations


class EnterpriseSetup:
    """Handles enterprise system setup"""

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.venv_path = self.project_root / "venv"

    def check_prerequisites(self):
        """Check if system prerequisites are installed"""
        logger.info("Checking system prerequisites...")

        # Check Python version
        if sys.version_info < (3, 8):
            raise RuntimeError("Python 3.8 or higher is required")

        logger.info(
            f"✓ Python {sys.version_info.major}.{sys.version_info.minor}")

        # Check if we can install packages
        try:
            import pip
            logger.info("✓ pip is available")
        except ImportError:
            raise RuntimeError("pip is not available")

        # Check for PostgreSQL client libraries
        try:
            import psycopg2
            logger.info("✓ PostgreSQL client libraries already installed")
        except ImportError:
            logger.warning(
                "⚠ PostgreSQL client libraries not found - will install")

        return True

    def install_dependencies(self, upgrade=False):
        """Install Python dependencies"""
        logger.info("Installing Python dependencies...")

        cmd = [sys.executable, "-m", "pip",
               "install", "-r", "requirements.txt"]
        if upgrade:
            cmd.append("--upgrade")

        try:
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True)
            logger.info("✓ Dependencies installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install dependencies: {e}")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")
            return False

    def check_postgresql_connection(self, host=None, port=None,
                                    database=None, user=None, password=None):
        """Check PostgreSQL connection"""
        logger.info("Testing PostgreSQL connection...")

        try:
            import psycopg2
            # Prefer DATABASE_URL if provided (commonly used in cloud deployments)
            db_url = os.getenv('DATABASE_URL')
            if db_url:
                logger.info("Using DATABASE_URL from environment")
                try:
                    with psycopg2.connect(db_url) as conn:
                        with conn.cursor() as cursor:
                            cursor.execute("SELECT version();")
                            version = cursor.fetchone()[0]
                            logger.info(
                                f"✓ Connected to PostgreSQL: {version}")
                            return True
                except Exception:
                    # Fall through to individual POSTGRES_* vars for more detailed error logging
                    logger.warning(
                        "Failed to connect with DATABASE_URL, falling back to POSTGRES_* env vars")

            # Fallback to individual POSTGRES_* environment variables
            host = host or os.getenv('POSTGRES_HOST', 'localhost')
            port = port or int(os.getenv('POSTGRES_PORT', 5432))
            database = database or os.getenv('POSTGRES_DB', 'imageprocessing')
            user = user or os.getenv('POSTGRES_USER', 'postgres')
            password = password or os.getenv('POSTGRES_PASSWORD', '')

            conn_string = f"host='{host}' port='{port}' dbname='{database}' user='{user}'"
            if password:
                conn_string += f" password='{password}'"

            with psycopg2.connect(conn_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()[0]
                    logger.info(f"✓ Connected to PostgreSQL: {version}")
                    return True

        except ImportError:
            logger.error("❌ psycopg2 not installed")
            return False
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            logger.info(
                "Make sure PostgreSQL is running and credentials are correct")
            return False

    def check_redis_connection(self, host=None, port=None, password=None):
        """Check Redis connection"""
        logger.info("Testing Redis connection...")

        try:
            import redis

            # Get connection parameters from environment
            host = host or os.getenv('REDIS_HOST', 'localhost')
            port = port or int(os.getenv('REDIS_PORT', 6379))
            password = password or os.getenv('REDIS_PASSWORD')

            client = redis.Redis(host=host, port=port,
                                 password=password, decode_responses=True)
            client.ping()

            info = client.info()
            logger.info(f"✓ Connected to Redis: {info['redis_version']}")
            return True

        except ImportError:
            logger.error("❌ redis package not installed")
            return False
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.info(
                "Make sure Redis is running and credentials are correct")
            return False

    def initialize_database(self, drop_existing=False):
        """Initialize the database schema"""
        logger.info("Initializing database schema...")

        try:
            from src.enterprise_config import config
            from src.database_models import db_manager

            # Drop tables if requested
            if drop_existing:
                logger.info("Dropping existing database tables...")
                db_manager.drop_tables()
                logger.info("✓ Existing tables dropped")

            # Create database tables
            db_manager.create_tables()

            # Run migrations for existing tables
            self.run_database_migrations()

            logger.info("✓ Database schema initialized")
            return True

        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            return False

    def run_database_migrations(self):
        """Run database migrations for existing tables"""
        logger.info("Running database migrations...")

        try:
            from src.enterprise_config import config

            # Get database connection
            db_config = config.get_database_config()

            # Support either a dict (kwargs for create_engine) or a URL string
            if isinstance(db_config, dict):
                engine = create_engine(**db_config)
            else:
                engine = create_engine(db_config)

            with engine.connect() as conn:
                # Define all the new listing data columns that need to be added
                new_columns = [
                    ('serial_number', 'VARCHAR(100)'),
                    ('business_name', 'VARCHAR(500)'),
                    ('input_phone_number', 'VARCHAR(50)'),
                    ('storefront_photo_url', 'TEXT'),
                    ('phone_number', 'BOOLEAN'),
                    # Phone match fields (added for phone matching feature)
                    ('phone_match_score', 'INTEGER'),
                    ('phone_match', 'VARCHAR(50)')
                ]

                # Check and add each missing column
                for column_name, column_type in new_columns:
                    result = conn.execute(text("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'url_analysis_results' 
                        AND column_name = :column_name
                    """), {"column_name": column_name})

                    if not result.fetchone():
                        logger.info(
                            f"Adding missing {column_name} column to url_analysis_results table...")
                        conn.execute(text(f"""
                            ALTER TABLE url_analysis_results 
                            ADD COLUMN {column_name} {column_type}
                        """))
                        conn.commit()
                        logger.info(f"✓ Added {column_name} column")
                    else:
                        logger.info(f"✓ {column_name} column already exists")

                # Add new indexes for performance
                indexes_to_create = [
                    ('idx_serial_number', 'serial_number'),
                    ('idx_business_name', 'business_name')
                ]

                for index_name, column_name in indexes_to_create:
                    try:
                        # Check if index exists
                        result = conn.execute(text("""
                            SELECT indexname 
                            FROM pg_indexes 
                            WHERE tablename = 'url_analysis_results' 
                            AND indexname = :index_name
                        """), {"index_name": index_name})

                        if not result.fetchone():
                            logger.info(f"Creating index {index_name}...")
                            conn.execute(text(f"""
                                CREATE INDEX {index_name} ON url_analysis_results ({column_name})
                            """))
                            conn.commit()
                            logger.info(f"✓ Created index {index_name}")
                        else:
                            logger.info(f"✓ Index {index_name} already exists")
                    except Exception as e:
                        logger.warning(
                            f"Could not create index {index_name}: {e}")

            engine.dispose()
            return True

        except Exception as e:
            logger.error(f"❌ Database migration failed: {e}")
            return False

    def create_config_file(self):
        """Create example configuration file"""
        logger.info("Creating example configuration...")
        config_content = """# Enterprise Image Processing Configuration
# Copy this file to .env and configure your settings

# Option A - Single DATABASE_URL (recommended for cloud/VM deployments)
DATABASE_URL=postgresql://analyzer_user:your_password_here@localhost:5432/image_analyzer

# Option B - Individual POSTGRES_* variables (alternative)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=image_analyzer
POSTGRES_USER=analyzer_user
POSTGRES_PASSWORD=your_password_here

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# OpenRouter API Configuration
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_PRESET=@preset/identify-storefront

# Processing Configuration
CHUNK_SIZE=500
MAX_CONCURRENT_BATCHES=5
MAX_CONCURRENT_WORKERS=16
REQUEST_TIMEOUT=90
RETRY_ATTEMPTS=2

# Application Configuration
SECRET_KEY=your-secret-key-here
MAX_UPLOAD_SIZE=104857600  # 100MB
DEBUG=false

# Directories
UPLOAD_DIR=./uploads
LOG_DIR=./logs
EXPORT_DIR=./exports
TEMP_DIR=./temp
"""

        config_path = self.project_root / ".env.example"
        with open(config_path, 'w') as f:
            f.write(config_content)

        logger.info(f"✓ Example configuration created at {config_path}")
        logger.info("Copy .env.example to .env and configure your settings")

        return True

    def create_directories(self):
        """Create necessary directories"""
        logger.info("Creating necessary directories...")

        directories = [
            "uploads",
            "logs",
            "exports",
            "temp",
            "backups"
        ]

        for dir_name in directories:
            dir_path = self.project_root / dir_name
            dir_path.mkdir(exist_ok=True)
            logger.info(f"✓ Created directory: {dir_path}")

        return True

    def test_openrouter_config(self):
        """Test OpenRouter configuration"""
        logger.info("Testing OpenRouter configuration...")

        api_key = os.getenv('OPENROUTER_API_KEY', '')
        if api_key and len(api_key) > 10:
            logger.info("✓ OpenRouter API key configured")
            return True
        else:
            logger.warning("⚠ OPENROUTER_API_KEY not configured or too short")
            return False

    def run_health_check(self):
        """Run comprehensive health check"""
        logger.info("=" * 60)
        logger.info("ENTERPRISE SYSTEM HEALTH CHECK")
        logger.info("=" * 60)

        checks = [
            ("Prerequisites", self.check_prerequisites),
            ("PostgreSQL", self.check_postgresql_connection),
            ("Redis", self.check_redis_connection),
            ("OpenRouter Config", self.test_openrouter_config),
        ]

        results = {}
        for name, check_func in checks:
            try:
                results[name] = check_func()
            except Exception as e:
                logger.error(f"❌ {name} check failed: {e}")
                results[name] = False

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("HEALTH CHECK SUMMARY")
        logger.info("=" * 60)

        for name, result in results.items():
            status = "✓ PASS" if result else "❌ FAIL"
            logger.info(f"{name:20} {status}")

        all_passed = all(results.values())
        if all_passed:
            logger.info("\n🎉 All health checks passed! System is ready.")
        else:
            logger.info(
                "\n⚠ Some health checks failed. Please fix issues before proceeding.")

        return all_passed

    def setup_development_environment(self):
        """Complete development environment setup"""
        logger.info("=" * 60)
        logger.info("ENTERPRISE DEVELOPMENT ENVIRONMENT SETUP")
        logger.info("=" * 60)

        steps = [
            ("Create directories", self.create_directories),
            ("Create config example", self.create_config_file),
            ("Install dependencies", self.install_dependencies),
            ("Initialize database", lambda: self.initialize_database(
                drop_existing=False)),
        ]

        for step_name, step_func in steps:
            logger.info(f"\nStep: {step_name}")
            try:
                success = step_func()
                if not success:
                    logger.error(f"❌ {step_name} failed")
                    return False
            except Exception as e:
                logger.error(f"❌ {step_name} failed with error: {e}")
                return False

        logger.info("\n🎉 Development environment setup complete!")
        logger.info("\nNext steps:")
        logger.info("1. Copy .env.example to .env and configure your settings")
        logger.info("2. Start PostgreSQL and Redis services")
        logger.info("3. Run health check: python setup.py --health-check")
        logger.info("4. Start the application: python -m src.enterprise_app")

        return True


def main():
    """Main setup function"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Enterprise Image Processing Setup")
    parser.add_argument("--health-check", action="store_true",
                        help="Run health check")
    parser.add_argument("--install-deps", action="store_true",
                        help="Install dependencies")
    parser.add_argument("--init-db", action="store_true",
                        help="Initialize database")
    parser.add_argument("--migrate-db", action="store_true",
                        help="Run database migrations")
    parser.add_argument("--create-config",
                        action="store_true", help="Create config file")
    parser.add_argument("--setup-dev", action="store_true",
                        help="Full development setup")
    parser.add_argument("--upgrade", action="store_true",
                        help="Upgrade dependencies")
    parser.add_argument("--drop-db", action="store_true",
                        help="Drop existing database tables")

    args = parser.parse_args()

    setup = EnterpriseSetup()

    try:
        if args.health_check:
            success = setup.run_health_check()
            sys.exit(0 if success else 1)

        elif args.install_deps:
            success = setup.install_dependencies(upgrade=args.upgrade)
            sys.exit(0 if success else 1)

        elif args.init_db:
            success = setup.initialize_database(drop_existing=args.drop_db)
            sys.exit(0 if success else 1)

        elif args.migrate_db:
            success = setup.run_database_migrations()
            sys.exit(0 if success else 1)

        elif args.create_config:
            success = setup.create_config_file()
            sys.exit(0 if success else 1)

        elif args.setup_dev:
            success = setup.setup_development_environment()
            sys.exit(0 if success else 1)

        else:
            parser.print_help()
            print("\nQuick start:")
            print("python setup.py --setup-dev    # Complete development setup")
            print("python setup.py --health-check # Check system status")

    except KeyboardInterrupt:
        logger.info("\nSetup interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
