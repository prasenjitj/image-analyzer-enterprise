"""
Configuration for enterprise-grade batch processing.
Supports PostgreSQL, Redis, OpenRouter API, and scalable architecture.
"""
import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class EnterpriseConfig(BaseSettings):
    """Enterprise configuration for batch processing"""

    # API Backend Selection: "openrouter" or "legacy"
    api_backend: str = Field("openrouter", env="API_BACKEND")

    # OpenRouter API Configuration (used when api_backend="openrouter")
    openrouter_api_key: str = Field("", env="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        "qwen/qwen-2.5-vl-7b-instruct", env="OPENROUTER_MODEL")
    openrouter_preset: str = Field(
        "@preset/identify-storefront", env="OPENROUTER_PRESET")
    openrouter_referer: str = Field(
        "https://image-analyzer-enterprise.com", env="OPENROUTER_REFERER")
    openrouter_site_title: str = Field(
        "Enterprise Image Analyzer", env="OPENROUTER_SITE_TITLE")

    # Legacy API Configuration (used when api_backend="legacy")
    # Single endpoint (backward compatible)
    legacy_api_endpoint: str = Field(
        "http://localhost:8000/generate", env="LEGACY_API_ENDPOINT")
    # Multiple endpoints for load balancing (comma-separated)
    legacy_api_endpoints: str = Field(
        "", env="LEGACY_API_ENDPOINTS")
    legacy_api_key: str = Field("", env="LEGACY_API_KEY")

    @property
    def legacy_api_endpoints_list(self) -> List[str]:
        """Return list of legacy API endpoints for load balancing"""
        # First check LEGACY_API_ENDPOINTS (comma-separated list)
        if self.legacy_api_endpoints:
            return [e.strip() for e in self.legacy_api_endpoints.split(',') if e.strip()]
        # Fall back to single endpoint
        if self.legacy_api_endpoint:
            return [self.legacy_api_endpoint]
        return []

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

    # Batch Processing Configuration - OPTIMIZED FOR THROUGHPUT
    # Reduced for better parallelism
    chunk_size: int = Field(500, env="CHUNK_SIZE")
    max_concurrent_batches: int = Field(5, env="MAX_CONCURRENT_BATCHES")
    # Process multiple chunks in parallel
    max_concurrent_chunks: int = Field(4, env="MAX_CONCURRENT_CHUNKS")
    chunk_processing_timeout: int = Field(
        1800, env="CHUNK_PROCESSING_TIMEOUT")  # 30 minutes
    # Maximum URLs per batch - CSVs with more records will be split into multiple batches
    max_batch_size: int = Field(5000, env="MAX_BATCH_SIZE")

    # Processing Configuration - OPTIMIZED TO MATCH LLM MODEL THROUGHPUT
    # The LLM model supports 16 concurrent inference workers with batch size 16
    # and 1000 req/min rate limit, so we should push high concurrency
    max_concurrent_workers: int = Field(16, env="MAX_CONCURRENT_WORKERS")
    # Reduced timeout since LLM model processes quickly with batching
    request_timeout: int = Field(90, env="REQUEST_TIMEOUT")
    retry_attempts: int = Field(2, env="RETRY_ATTEMPTS")
    retry_delay: float = Field(1.0, env="RETRY_DELAY")  # Faster retries

    # Rate Limiting - Matched to LLM model's 1000 req/min capacity
    requests_per_minute: int = Field(
        # 80% of LLM model's 1000/min limit for safety margin
        800, env="REQUESTS_PER_MINUTE")
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

    # Performance Tuning - Optimized for high throughput with LLM model
    image_max_size: int = Field(2048, env="IMAGE_MAX_SIZE")
    memory_limit_gb: int = Field(8, env="MEMORY_LIMIT_GB")
    gc_frequency: int = Field(1000, env="GC_FREQUENCY")
    # Increased to match LLM model's 16 concurrent inference workers
    max_concurrent_requests: int = Field(16, env="MAX_CONCURRENT_REQUESTS")
    # Connection pool size for aiohttp
    connection_pool_size: int = Field(100, env="CONNECTION_POOL_SIZE")
    # Keep-alive connections to reduce TCP overhead
    enable_keepalive: bool = Field(True, env="ENABLE_KEEPALIVE")

    # Background Job Configuration
    job_queue_name: str = Field("image_analysis_jobs", env="JOB_QUEUE_NAME")
    job_retry_attempts: int = Field(2, env="JOB_RETRY_ATTEMPTS")
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

    # Store front fuzzy-match configuration
    # Thresholds are percentages (0-100)
    store_front_match_threshold_match: int = Field(
        80, env="STORE_FRONT_MATCH_THRESHOLD_MATCH")
    store_front_match_threshold_partial: int = Field(
        70, env="STORE_FRONT_MATCH_THRESHOLD_PARTIAL")
    # Use rapidfuzz token_set_ratio when available. If False, falls back to difflib.SequenceMatcher
    store_front_match_use_rapidfuzz: bool = Field(
        True, env="STORE_FRONT_MATCH_USE_RAPIDFUZZ")
    # Comma-separated list of common business suffixes to strip before matching
    store_front_match_strip_suffixes: str = Field(
        "ltd,llc,inc,pvt,pvtltd,co,company,store,stores,the,shop,shops,retail",
        env="STORE_FRONT_MATCH_STRIP_SUFFIXES"
    )

    @property
    def store_front_match_strip_suffixes_list(self) -> List[str]:
        """Return normalized list of suffixes to strip during store name normalization"""
        raw = (self.store_front_match_strip_suffixes or '')
        return [s.strip().lower() for s in raw.split(',') if s.strip()]

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

        # API Backend validation
        if self.api_backend not in ("openrouter", "legacy"):
            warnings.append(
                f"Invalid API_BACKEND '{self.api_backend}' - must be 'openrouter' or 'legacy'")

        # OpenRouter API validation (only when using OpenRouter backend)
        if self.api_backend == "openrouter" and not self.openrouter_api_key:
            warnings.append(
                "OPENROUTER_API_KEY not set - image processing will fail")

        # Legacy API validation (only when using legacy backend)
        if self.api_backend == "legacy" and not self.legacy_api_endpoint:
            warnings.append(
                "LEGACY_API_ENDPOINT not set - image processing will fail")

        # Performance validation
        if self.max_concurrent_workers > 100:
            warnings.append(
                "High concurrent workers may impact system performance")

        if self.chunk_size > 2000:
            warnings.append("Large chunk size may cause memory issues")

        # Validate store front match thresholds
        if not (0 <= self.store_front_match_threshold_partial <= 100 and 0 <= self.store_front_match_threshold_match <= 100):
            warnings.append(
                "Store front match thresholds must be between 0 and 100")
        if self.store_front_match_threshold_partial > self.store_front_match_threshold_match:
            warnings.append(
                "Partial match threshold is greater than full match threshold; check STORE_FRONT_MATCH_THRESHOLD_* settings")

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
