"""
PostgreSQL database models for enterprise batch processing
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from enum import Enum as PyEnum
import json
import uuid

from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime, Boolean,
    Text, JSON, Float, ForeignKey, Enum, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .enterprise_config import config

Base = declarative_base()


class BatchStatus(PyEnum):
    """Batch processing status enumeration"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChunkStatus(PyEnum):
    """Chunk processing status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class ProcessingBatch(Base):
    """Main batch processing table"""
    __tablename__ = 'processing_batches'

    # Primary identification
    batch_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_name = Column(String(255), nullable=False)

    # Batch configuration
    total_urls = Column(Integer, nullable=False)
    chunk_size = Column(Integer, default=1000)
    total_chunks = Column(Integer, nullable=False)

    # Progress tracking
    processed_count = Column(Integer, default=0)
    successful_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    current_chunk = Column(Integer, default=0)

    # Status and timing
    status = Column(Enum(BatchStatus),
                    default=BatchStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    paused_at = Column(DateTime(timezone=True), nullable=True)

    # Performance metrics
    estimated_completion = Column(DateTime(timezone=True), nullable=True)
    processing_rate = Column(Float, default=0.0)  # URLs per minute
    success_rate = Column(Float, default=0.0)  # Percentage

    # Configuration and metadata
    original_filename = Column(String(255), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    # Store processing parameters
    processing_config = Column(JSON, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

    # Relationships
    chunks = relationship(
        "ProcessingChunk", back_populates="batch", cascade="all, delete-orphan")

    # Indexes for performance
    __table_args__ = (
        Index('idx_batch_status', 'status'),
        Index('idx_batch_created', 'created_at'),
        Index('idx_batch_status_created', 'status', 'created_at'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert batch to dictionary"""
        return {
            'batch_id': str(self.batch_id),
            'batch_name': self.batch_name,
            'total_urls': self.total_urls,
            'chunk_size': self.chunk_size,
            'total_chunks': self.total_chunks,
            'processed_count': self.processed_count,
            'successful_count': self.successful_count,
            'failed_count': self.failed_count,
            'current_chunk': self.current_chunk,
            'progress_percentage': self.progress_percentage,
            'status': self.status.value,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'estimated_completion': self.estimated_completion.isoformat() if self.estimated_completion else None,
            'processing_rate': self.processing_rate,
            'success_rate': self.success_rate,
            'original_filename': self.original_filename,
            'error_message': self.error_message,
            'retry_count': self.retry_count
        }

    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage"""
        if self.total_urls == 0:
            return 0.0
        return (self.processed_count / self.total_urls) * 100

    @property
    def is_active(self) -> bool:
        """Check if batch is actively processing"""
        return self.status in [BatchStatus.PENDING, BatchStatus.QUEUED, BatchStatus.PROCESSING]

    @property
    def is_complete(self) -> bool:
        """Check if batch is complete"""
        return self.status in [BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED]


class ProcessingChunk(Base):
    """Individual chunk processing table"""
    __tablename__ = 'processing_chunks'

    # Primary identification
    chunk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey(
        'processing_batches.batch_id'), nullable=False)
    chunk_number = Column(Integer, nullable=False)

    # Chunk data
    urls = Column(JSON, nullable=False)  # List of URLs in this chunk
    url_count = Column(Integer, nullable=False)

    # Progress tracking
    processed_count = Column(Integer, default=0)
    successful_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # Status and timing
    status = Column(Enum(ChunkStatus),
                    default=ChunkStatus.PENDING, nullable=False)
    queued_at = Column(DateTime(timezone=True), default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Performance metrics
    processing_time_seconds = Column(Float, nullable=True)
    average_time_per_url = Column(Float, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    # List of failed URLs with error details
    failed_urls = Column(JSON, nullable=True)

    # Worker information
    worker_id = Column(String(100), nullable=True)

    # Relationships
    batch = relationship("ProcessingBatch", back_populates="chunks")

    # Indexes for performance
    __table_args__ = (
        Index('idx_chunk_batch_id', 'batch_id'),
        Index('idx_chunk_status', 'status'),
        Index('idx_chunk_batch_number', 'batch_id', 'chunk_number'),
        Index('idx_chunk_queued', 'queued_at'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert chunk to dictionary"""
        return {
            'chunk_id': str(self.chunk_id),
            'batch_id': str(self.batch_id),
            'chunk_number': self.chunk_number,
            'url_count': self.url_count,
            'processed_count': self.processed_count,
            'successful_count': self.successful_count,
            'failed_count': self.failed_count,
            'status': self.status.value,
            'queued_at': self.queued_at.isoformat() if self.queued_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'processing_time_seconds': self.processing_time_seconds,
            'average_time_per_url': self.average_time_per_url,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'worker_id': self.worker_id
        }

    @property
    def progress_percentage(self) -> float:
        """Calculate chunk progress percentage"""
        if self.url_count == 0:
            return 0.0
        return (self.processed_count / self.url_count) * 100


class URLAnalysisResult(Base):
    """Enhanced URL analysis results table"""
    __tablename__ = 'url_analysis_results'

    # Primary identification
    result_id = Column(UUID(as_uuid=True),
                       primary_key=True, default=uuid.uuid4)
    url = Column(Text, nullable=False)
    # SHA256 hash for faster lookups
    url_hash = Column(String(64), nullable=False)

    # Batch tracking
    batch_id = Column(UUID(as_uuid=True), ForeignKey(
        'processing_batches.batch_id'), nullable=True)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey(
        'processing_chunks.chunk_id'), nullable=True)

    # Analysis results
    analysis_result = Column(JSON, nullable=True)
    store_image = Column(Boolean, nullable=True)
    text_content = Column(Text, nullable=True)
    store_name = Column(String(255), nullable=True)
    business_contact = Column(Text, nullable=True)
    phone_number = Column(Boolean, nullable=True)
    image_description = Column(Text, nullable=True)

    # Processing metadata
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    processing_time_seconds = Column(Float, nullable=True)
    # Track which API key was used
    api_key_used = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True),
                        default=func.now(), onupdate=func.now())

    # Cache information
    cache_hit = Column(Boolean, default=False)

    # Indexes for performance
    __table_args__ = (
        Index('idx_url_hash', 'url_hash'),
        Index('idx_batch_id', 'batch_id'),
        Index('idx_chunk_id', 'chunk_id'),
        Index('idx_success_created', 'success', 'created_at'),
        Index('idx_url_hash_batch', 'url_hash', 'batch_id'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary"""
        return {
            'result_id': str(self.result_id),
            'url': self.url,
            'batch_id': str(self.batch_id) if self.batch_id else None,
            'chunk_id': str(self.chunk_id) if self.chunk_id else None,
            'analysis_result': self.analysis_result,
            'store_image': self.store_image,
            'text_content': self.text_content,
            'store_name': self.store_name,
            'business_contact': self.business_contact,
            'phone_number': self.phone_number,
            'image_description': self.image_description,
            'success': self.success,
            'error_message': self.error_message,
            'processing_time_seconds': self.processing_time_seconds,
            'api_key_used': self.api_key_used,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'cache_hit': self.cache_hit
        }


class DatabaseManager:
    """Database connection and session management"""

    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database connection"""
        db_config = config.get_database_config()
        self.engine = create_engine(**db_config)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self):
        """Create all database tables"""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop all database tables (use with caution)"""
        Base.metadata.drop_all(bind=self.engine)

    def get_session(self) -> Session:
        """Get database session"""
        return self.SessionLocal()

    def close(self):
        """Close database connections"""
        if self.engine:
            self.engine.dispose()


# Global database manager instance
db_manager = DatabaseManager()


def get_db_session() -> Session:
    """Get database session with context management"""
    session = db_manager.get_session()
    try:
        yield session
    finally:
        session.close()


def init_database():
    """Initialize database tables"""
    db_manager.create_tables()
    print("✅ Database tables created successfully")
