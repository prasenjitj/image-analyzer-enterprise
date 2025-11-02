"""
Redis-based background job system for batch processing
"""
import json
import logging
import time
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib

try:
    import redis
    from redis import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from enterprise_config import config

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Job status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """Background job data structure"""
    job_id: str
    job_type: str
    payload: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    priority: int = 0  # Higher numbers = higher priority

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for Redis storage"""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        for field in ['created_at', 'started_at', 'completed_at']:
            if data[field]:
                data[field] = data[field].isoformat()
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Job':
        """Create job from dictionary"""
        # Convert ISO strings back to datetime
        for field in ['created_at', 'started_at', 'completed_at']:
            if data.get(field):
                data[field] = datetime.fromisoformat(data[field])

        if 'status' in data:
            data['status'] = JobStatus(data['status'])

        return cls(**data)


class JobQueue:
    """Redis-based job queue manager"""

    def __init__(self, redis_client: Redis = None):
        self.redis_client = redis_client or self._create_redis_client()
        self.queue_name = config.job_queue_name
        self.processing_set = f"{self.queue_name}:processing"
        self.completed_set = f"{self.queue_name}:completed"
        self.failed_set = f"{self.queue_name}:failed"
        self.job_data_prefix = f"{self.queue_name}:job:"

        if not REDIS_AVAILABLE:
            logger.warning("Redis not available, using in-memory fallback")
            self._jobs = {}  # In-memory fallback

    def _create_redis_client(self) -> Optional[Redis]:
        """Create Redis client"""
        if not REDIS_AVAILABLE:
            return None

        try:
            redis_config = config.get_redis_config()
            client = redis.from_url(**redis_config)
            client.ping()  # Test connection
            logger.info("Redis connection established")
            return client
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return None

    def enqueue_job(self, job_type: str, payload: Dict[str, Any],
                    priority: int = 0, max_retries: int = 3) -> str:
        """Add job to queue"""
        job_id = str(uuid.uuid4())

        job = Job(
            job_id=job_id,
            job_type=job_type,
            payload=payload,
            priority=priority,
            max_retries=max_retries
        )

        if self.redis_client:
            # Store job data
            job_key = f"{self.job_data_prefix}{job_id}"
            self.redis_client.setex(
                job_key,
                86400,  # 24 hours TTL
                json.dumps(job.to_dict())
            )

            # Add to priority queue (higher score = higher priority)
            self.redis_client.zadd(self.queue_name, {job_id: priority})
        else:
            # In-memory fallback
            self._jobs[job_id] = job

        logger.info(f"Enqueued job {job_id} of type {job_type}")
        return job_id

    def dequeue_job(self, worker_id: str) -> Optional[Job]:
        """Get next job from queue"""
        if self.redis_client:
            # Get highest priority job
            result = self.redis_client.zpopmax(self.queue_name)
            if not result:
                return None

            job_id, priority = result[0]
            job_key = f"{self.job_data_prefix}{job_id}"
            job_data = self.redis_client.get(job_key)

            if not job_data:
                logger.warning(f"Job data not found for {job_id}")
                return None

            job = Job.from_dict(json.loads(job_data))
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now()
            job.worker_id = worker_id

            # Move to processing set
            self.redis_client.sadd(self.processing_set, job_id)
            self.redis_client.setex(job_key, 86400, json.dumps(job.to_dict()))

            return job
        else:
            # In-memory fallback
            for job_id, job in self._jobs.items():
                if job.status == JobStatus.PENDING:
                    job.status = JobStatus.PROCESSING
                    job.started_at = datetime.now()
                    job.worker_id = worker_id
                    return job
            return None

    def complete_job(self, job_id: str, result: Dict[str, Any] = None):
        """Mark job as completed"""
        job = self.get_job(job_id)
        if not job:
            return

        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now()
        if result:
            job.payload['result'] = result

        if self.redis_client:
            job_key = f"{self.job_data_prefix}{job_id}"
            self.redis_client.setex(job_key, 86400, json.dumps(job.to_dict()))
            self.redis_client.srem(self.processing_set, job_id)
            self.redis_client.sadd(self.completed_set, job_id)
        else:
            self._jobs[job_id] = job

        logger.info(f"Completed job {job_id}")

    def fail_job(self, job_id: str, error_message: str, retry: bool = True):
        """Mark job as failed"""
        job = self.get_job(job_id)
        if not job:
            return

        job.error_message = error_message
        job.retry_count += 1

        if retry and job.retry_count <= job.max_retries:
            # Retry job
            job.status = JobStatus.RETRYING
            # Exponential backoff, max 5 min
            delay = min(300, 60 * (2 ** job.retry_count))

            if self.redis_client:
                # Re-queue with delay
                retry_time = time.time() + delay
                self.redis_client.zadd(f"{self.queue_name}:retry", {
                                       job_id: retry_time})
            else:
                job.status = JobStatus.PENDING  # Immediate retry in memory

            logger.warning(
                f"Retrying job {job_id} (attempt {job.retry_count}/{job.max_retries})")
        else:
            # Permanent failure
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()

            if self.redis_client:
                self.redis_client.srem(self.processing_set, job_id)
                self.redis_client.sadd(self.failed_set, job_id)

            logger.error(f"Failed job {job_id}: {error_message}")

        if self.redis_client:
            job_key = f"{self.job_data_prefix}{job_id}"
            self.redis_client.setex(job_key, 86400, json.dumps(job.to_dict()))
        else:
            self._jobs[job_id] = job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        if self.redis_client:
            job_key = f"{self.job_data_prefix}{job_id}"
            job_data = self.redis_client.get(job_key)
            if job_data:
                return Job.from_dict(json.loads(job_data))
        else:
            return self._jobs.get(job_id)
        return None

    def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics"""
        if self.redis_client:
            pending_count = self.redis_client.zcard(self.queue_name)
            processing_count = self.redis_client.scard(self.processing_set)
            completed_count = self.redis_client.scard(self.completed_set)
            failed_count = self.redis_client.scard(self.failed_set)
            retry_count = self.redis_client.zcard(f"{self.queue_name}:retry")
        else:
            jobs = list(self._jobs.values())
            pending_count = sum(
                1 for job in jobs if job.status == JobStatus.PENDING)
            processing_count = sum(
                1 for job in jobs if job.status == JobStatus.PROCESSING)
            completed_count = sum(
                1 for job in jobs if job.status == JobStatus.COMPLETED)
            failed_count = sum(
                1 for job in jobs if job.status == JobStatus.FAILED)
            retry_count = sum(
                1 for job in jobs if job.status == JobStatus.RETRYING)

        return {
            'pending': pending_count,
            'processing': processing_count,
            'completed': completed_count,
            'failed': failed_count,
            'retrying': retry_count
        }

    def cleanup_old_jobs(self, days: int = 7):
        """Clean up old completed/failed jobs"""
        cutoff_time = datetime.now() - timedelta(days=days)

        if self.redis_client:
            # Get all completed and failed jobs
            all_job_ids = set()
            all_job_ids.update(self.redis_client.smembers(self.completed_set))
            all_job_ids.update(self.redis_client.smembers(self.failed_set))

            for job_id in all_job_ids:
                job = self.get_job(job_id)
                if job and job.completed_at and job.completed_at < cutoff_time:
                    job_key = f"{self.job_data_prefix}{job_id}"
                    self.redis_client.delete(job_key)
                    self.redis_client.srem(self.completed_set, job_id)
                    self.redis_client.srem(self.failed_set, job_id)
        else:
            # Clean up in-memory jobs
            to_delete = []
            for job_id, job in self._jobs.items():
                if (job.status in [JobStatus.COMPLETED, JobStatus.FAILED] and
                        job.completed_at and job.completed_at < cutoff_time):
                    to_delete.append(job_id)

            for job_id in to_delete:
                del self._jobs[job_id]

        logger.info(f"Cleaned up jobs older than {days} days")


class BackgroundWorker:
    """Background worker for processing jobs"""

    def __init__(self, worker_id: str = None, job_handlers: Dict[str, Callable] = None):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.job_queue = JobQueue()
        self.job_handlers = job_handlers or {}
        self.running = False
        self.processed_count = 0

    def register_handler(self, job_type: str, handler: Callable):
        """Register job handler function"""
        self.job_handlers[job_type] = handler
        logger.info(f"Registered handler for job type: {job_type}")

    def start(self):
        """Start processing jobs"""
        self.running = True
        logger.info(f"Worker {self.worker_id} started")

        while self.running:
            try:
                job = self.job_queue.dequeue_job(self.worker_id)

                if job:
                    self.process_job(job)
                    self.processed_count += 1
                else:
                    # No jobs available, wait a bit
                    time.sleep(1)

            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(5)  # Wait before retrying

        logger.info(
            f"Worker {self.worker_id} stopped after processing {self.processed_count} jobs")

    def stop(self):
        """Stop processing jobs"""
        self.running = False

    def process_job(self, job: Job):
        """Process a single job"""
        logger.info(f"Processing job {job.job_id} of type {job.job_type}")

        try:
            handler = self.job_handlers.get(job.job_type)
            if not handler:
                raise ValueError(
                    f"No handler registered for job type: {job.job_type}")

            # Execute job handler
            result = handler(job.payload)

            # Mark job as completed
            self.job_queue.complete_job(job.job_id, result)

        except Exception as e:
            error_message = f"Job processing failed: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_message)
            self.job_queue.fail_job(job.job_id, error_message)


# Global job queue instance
job_queue = JobQueue()


def enqueue_chunk_processing(batch_id: str, chunk_id: str, urls: List[str]) -> str:
    """Enqueue chunk processing job"""
    payload = {
        'batch_id': batch_id,
        'chunk_id': chunk_id,
        'urls': urls,
        'chunk_size': len(urls)
    }

    return job_queue.enqueue_job('chunk_processing', payload, priority=1)


def enqueue_batch_finalization(batch_id: str) -> str:
    """Enqueue batch finalization job"""
    payload = {
        'batch_id': batch_id
    }

    return job_queue.enqueue_job('finalize_batch', payload, priority=2)


def start_background_workers(num_workers: int = None) -> List[BackgroundWorker]:
    """Start background workers for processing jobs"""
    if num_workers is None:
        num_workers = config.max_concurrent_workers or 4

    workers = []

    for i in range(num_workers):
        worker = BackgroundWorker(f"worker-{i+1}")

        # Register job handlers (these would be imported from other modules)
        try:
            from .batch_manager import process_chunk_handler, finalize_batch_handler
            worker.register_handler('process_chunk', process_chunk_handler)
            worker.register_handler('finalize_batch', finalize_batch_handler)
        except ImportError:
            logger.warning("Batch processing handlers not available")

        workers.append(worker)
        logger.info(f"Created worker {worker.worker_id}")

    return workers
