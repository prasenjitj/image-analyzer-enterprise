"""
Enhanced configuration for enterprise-grade batch processing
Supports PostgreSQL, Redis, and scalable architecture
"""
import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class EnterpriseConfig(BaseSettings):
    """Enterprise configuration for batch processing"""

    # API Configuration
    api_endpoint_url: str = Field(
        "http://localhost:8000/generate", env="API_ENDPOINT_URL")
    # Kept for backward compatibility
    google_api_key: str = Field("", env="GOOGLE_API_KEY")
    google_api_keys: Optional[str] = Field(
        None, env="GOOGLE_API_KEYS")  # Kept for backward compatibility

    # Database Configuration (PostgreSQL)
    database_url: str = Field(
        "postgresql://user:password@localhost:5432/image_analyzer",
        env="DATABASE_URL"
    )
    database_pool_size: int = Field(20, env="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(30, env="DATABASE_MAX_OVERFLOW")
    database_echo: bool = Field(False, env="DATABASE_ECHO")

    # Redis Configuration
    redis_url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    redis_password: Optional[str] = Field(None, env="REDIS_PASSWORD")
    redis_db: int = Field(0, env="REDIS_DB")
    redis_socket_timeout: int = Field(5, env="REDIS_SOCKET_TIMEOUT")

    # Batch Processing Configuration
    chunk_size: int = Field(1000, env="CHUNK_SIZE")
    max_concurrent_batches: int = Field(5, env="MAX_CONCURRENT_BATCHES")
    max_concurrent_chunks: int = Field(3, env="MAX_CONCURRENT_CHUNKS")
    chunk_processing_timeout: int = Field(
        1800, env="CHUNK_PROCESSING_TIMEOUT")  # 30 minutes

    # Processing Configuration
    max_concurrent_workers: int = Field(50, env="MAX_CONCURRENT_WORKERS")
    request_timeout: int = Field(30, env="REQUEST_TIMEOUT")
    retry_attempts: int = Field(3, env="RETRY_ATTEMPTS")
    retry_delay: float = Field(2.0, env="RETRY_DELAY")

    # Rate Limiting (Single API Key Foundation)
    requests_per_minute: int = Field(
        55, env="REQUESTS_PER_MINUTE")  # Conservative
    rate_limit_buffer: float = Field(0.1, env="RATE_LIMIT_BUFFER")

    # Progress and Monitoring
    progress_update_interval: int = Field(
        10, env="PROGRESS_UPDATE_INTERVAL")  # seconds
    batch_cleanup_days: int = Field(30, env="BATCH_CLEANUP_DAYS")
    enable_monitoring: bool = Field(True, env="ENABLE_MONITORING")
    monitoring_port: int = Field(8080, env="MONITORING_PORT")

    # Storage Configuration
    upload_dir: str = Field("./uploads", env="UPLOAD_DIR")
    export_dir: str = Field("./exports", env="EXPORT_DIR")
    log_dir: str = Field("./logs", env="LOG_DIR")
    temp_dir: str = Field("./temp", env="TEMP_DIR")

    # Application Configuration
    secret_key: str = Field(
        "dev-secret-key-change-in-production", env="SECRET_KEY")
    max_upload_size: int = Field(104857600, env="MAX_UPLOAD_SIZE")  # 100MB

    # Cache Configuration
    cache_db_path: str = Field("./temp/analysis_cache.db", env="CACHE_DB_PATH")

    # Performance Tuning
    image_max_size: int = Field(2048, env="IMAGE_MAX_SIZE")
    memory_limit_gb: int = Field(8, env="MEMORY_LIMIT_GB")
    gc_frequency: int = Field(1000, env="GC_FREQUENCY")
    max_concurrent_requests: int = Field(10, env="MAX_CONCURRENT_REQUESTS")

    # Background Job Configuration
    job_queue_name: str = Field("image_analysis_jobs", env="JOB_QUEUE_NAME")
    job_retry_attempts: int = Field(3, env="JOB_RETRY_ATTEMPTS")
    job_retry_delay: int = Field(60, env="JOB_RETRY_DELAY")  # seconds
    worker_timeout: int = Field(3600, env="WORKER_TIMEOUT")  # 1 hour

    # Export Configuration
    max_export_rows: int = Field(1000000, env="MAX_EXPORT_ROWS")  # 1M rows
    export_chunk_size: int = Field(10000, env="EXPORT_CHUNK_SIZE")
    export_timeout: int = Field(300, env="EXPORT_TIMEOUT")  # 5 minutes

    # Development/Testing
    development_mode: bool = Field(False, env="DEVELOPMENT_MODE")
    enable_debug_logging: bool = Field(False, env="ENABLE_DEBUG_LOGGING")
    skip_image_download: bool = Field(False, env="SKIP_IMAGE_DOWNLOAD")
    # Whether to always upload downloaded image bytes to the API (instead of
    # sending only the image URL). Useful when the API expects a file upload.
    upload_always: bool = Field(False, env="UPLOAD_ALWAYS")
    # In development mode, store the actual image bytes that are sent to the
    # remote API so developers can inspect what was uploaded.
    store_sent_images: bool = Field(False, env="STORE_SENT_IMAGES")

    @property
    def api_keys_list(self) -> List[str]:
        """Get list of API keys (for backward compatibility, returns empty list if using external API)"""
        if self.google_api_keys:
            keys = [key.strip() for key in self.google_api_keys.split(',')]
            return [k for k in keys if k]
        elif self.google_api_key:
            return [self.google_api_key.strip()]
        return []  # External API endpoint doesn't need API keys

    @property
    def is_postgresql(self) -> bool:
        """Check if using PostgreSQL"""
        return self.database_url.startswith('postgresql')

    @property
    def is_redis_available(self) -> bool:
        """Check if Redis is configured"""
        return bool(self.redis_url)

    @property
    def max_workers(self) -> int:
        """Alias for max_concurrent_workers for backward compatibility"""
        return self.max_concurrent_workers

    def create_directories(self):
        """Create necessary directories"""
        directories = [
            self.upload_dir,
            self.export_dir,
            self.log_dir,
            self.temp_dir
        ]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)

    def get_database_config(self) -> dict:
        """Get database configuration for SQLAlchemy"""
        return {
            'url': self.database_url,
            'pool_size': self.database_pool_size,
            'max_overflow': self.database_max_overflow,
            'echo': self.database_echo,
            'pool_pre_ping': True,
            'pool_recycle': 3600
        }

    def get_redis_config(self) -> dict:
        """Get Redis configuration"""
        config = {
            'url': self.redis_url,
            'db': self.redis_db,
            'socket_timeout': self.redis_socket_timeout,
            'decode_responses': True
        }

        if self.redis_password:
            config['password'] = self.redis_password

        return config

    def validate_configuration(self) -> List[str]:
        """Validate configuration and return warnings"""
        warnings = []

        # Database validation
        if not self.is_postgresql and not self.development_mode:
            warnings.append("PostgreSQL recommended for production use")

        # Redis validation
        if not self.is_redis_available:
            warnings.append("Redis required for background job processing")

        # API key validation
        if len(self.api_keys_list) == 1:
            warnings.append(
                "Single API key may limit processing speed for large batches")

        # Performance validation
        if self.max_concurrent_workers > 100:
            warnings.append(
                "High concurrent workers may impact system performance")

        if self.chunk_size > 2000:
            warnings.append("Large chunk size may cause memory issues")

        return warnings


# Global configuration instance
config = EnterpriseConfig()

# Validate configuration on import
if config.enable_debug_logging:
    warnings = config.validate_configuration()
    if warnings:
        import logging
        logger = logging.getLogger(__name__)
        for warning in warnings:
            logger.warning(f"Configuration warning: {warning}")
