"""
Pytest configuration file.
Adds the project root to Python path so 'src' package can be imported.
"""
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to Python path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Set environment variables for testing before any src imports
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('MAX_UPLOAD_SIZE', '104857600')
os.environ.setdefault('CHUNK_SIZE', '500')
os.environ.setdefault('MAX_BATCH_SIZE', '5000')
