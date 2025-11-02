"""
Background worker process for enterprise image processing

Handles chunk processing through the job queue system with Gemini AI integration,
progress tracking, retry logic, and error handling.
"""
import asyncio
import logging
import time
import signal
import sys
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from enterprise_config import config
from database_models import (
    ProcessingBatch, ProcessingChunk, URLAnalysisResult,
    BatchStatus, ChunkStatus, db_manager
)
from job_queue import job_queue, Job
from processor import ImageProcessor
from cache import get_cache

logger = logging.getLogger(__name__)


class ChunkProcessor:
    """Processes individual chunks of URLs"""

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.processor = ImageProcessor(
            api_keys=config.api_keys_list,
            max_workers=config.max_concurrent_requests,
            image_max_size=config.image_max_size
        )
        self.cache = get_cache(config.cache_db_path)
        self.should_stop = False

        logger.info(f"ChunkProcessor {worker_id} initialized")

    async def process_chunk(self, batch_id: str, chunk_id: str, urls: List[str]) -> Dict[str, Any]:
        """Process a chunk of URLs"""
        chunk_start_time = time.time()

        logger.info(
            f"Worker {self.worker_id} processing chunk {chunk_id} with {len(urls)} URLs")

        # Update chunk status to processing
        self._update_chunk_status(
            chunk_id, ChunkStatus.PROCESSING, started_at=datetime.now())

        try:
            # Filter URLs that need processing (not in cache)
            urls_to_process = self.cache.batch_get_missing_urls(urls)

            if len(urls_to_process) < len(urls):
                cache_hits = len(urls) - len(urls_to_process)
                logger.info(
                    f"Chunk {chunk_id}: {cache_hits} URLs found in cache, processing {len(urls_to_process)} new URLs")

            # Process URLs in batches
            all_results = []

            if urls_to_process:
                # Start the processor
                self.processor.start_processing()

                # Process in smaller batches for better progress tracking
                batch_size = min(100, len(urls_to_process))

                for i in range(0, len(urls_to_process), batch_size):
                    if self.should_stop:
                        logger.info(
                            f"Chunk {chunk_id} processing stopped by signal")
                        break

                    batch_urls = urls_to_process[i:i + batch_size]
                    logger.debug(
                        f"Processing sub-batch {i//batch_size + 1} of chunk {chunk_id}")

                    # Process batch of URLs
                    batch_results = await self.processor.process_batch(batch_urls)
                    all_results.extend(batch_results)

                    # Update progress
                    processed_so_far = len(all_results)
                    self._update_chunk_progress(
                        chunk_id, processed_so_far, len(urls_to_process))

            # Get cached results for URLs that were already processed
            cached_results = []
            for url in urls:
                if url not in urls_to_process:
                    cached_analysis = self.cache.get_analysis(url)
                    if cached_analysis:
                        # Create a result object from cached data
                        cached_result = type('CachedResult', (), {
                            'url': url,
                            'success': True,
                            'analysis': cached_analysis,
                            'error': None,
                            'processing_time': 0.0
                        })()
                        cached_results.append(cached_result)

            all_results.extend(cached_results)

            # Store results in database
            self._store_chunk_results(batch_id, chunk_id, all_results)

            # Calculate statistics
            successful_count = sum(1 for r in all_results if r.success)
            failed_count = len(all_results) - successful_count
            processing_time = time.time() - chunk_start_time

            # Update chunk completion
            self._update_chunk_status(
                chunk_id,
                ChunkStatus.COMPLETED,
                completed_at=datetime.now(),
                processed_count=len(all_results),
                successful_count=successful_count,
                failed_count=failed_count,
                processing_time_seconds=processing_time
            )

            # Update batch progress
            self._update_batch_progress(batch_id)

            logger.info(
                f"Chunk {chunk_id} completed: {successful_count} successful, {failed_count} failed, {processing_time:.1f}s")

            return {
                'chunk_id': chunk_id,
                'processed_count': len(all_results),
                'successful_count': successful_count,
                'failed_count': failed_count,
                'processing_time': processing_time,
                'cache_hits': len(cached_results)
            }

        except Exception as e:
            logger.error(f"Error processing chunk {chunk_id}: {e}")

            # Update chunk as failed
            self._update_chunk_status(
                chunk_id,
                ChunkStatus.FAILED,
                completed_at=datetime.now(),
                error_message=str(e),
                processing_time_seconds=time.time() - chunk_start_time
            )

            # Update batch progress
            self._update_batch_progress(batch_id)

            raise

    def _update_chunk_status(self, chunk_id: str, status: ChunkStatus, **kwargs):
        """Update chunk status in database"""
        with db_manager.get_session() as session:
            chunk = session.query(ProcessingChunk).filter_by(
                chunk_id=chunk_id).first()
            if chunk:
                chunk.status = status

                # Update provided fields
                for field, value in kwargs.items():
                    if hasattr(chunk, field):
                        setattr(chunk, field, value)

                session.commit()

    def _update_chunk_progress(self, chunk_id: str, processed_count: int, total_count: int):
        """Update chunk processing progress"""
        with db_manager.get_session() as session:
            chunk = session.query(ProcessingChunk).filter_by(
                chunk_id=chunk_id).first()
            if chunk:
                chunk.processed_count = processed_count
                # Progress percentage is calculated by the model property
                session.commit()

    def _store_chunk_results(self, batch_id: str, chunk_id: str, results: List[Any]):
        """Store processing results in database"""
        with db_manager.get_session() as session:
            for result in results:
                try:
                    # Generate URL hash for database constraint
                    url_hash = hashlib.sha256(
                        result.url.encode('utf-8')).hexdigest()

                    # Check if this URL already has a result for this batch
                    existing = session.query(URLAnalysisResult).filter_by(
                        batch_id=batch_id,
                        url_hash=url_hash
                    ).first()

                    if existing:
                        logger.debug(
                            f"Skipping duplicate URL result: {result.url}")
                        continue

                    # Create URLAnalysisResult record
                    url_result = URLAnalysisResult(
                        batch_id=batch_id,
                        chunk_id=chunk_id,
                        url=result.url,
                        url_hash=url_hash,
                        success=result.success,
                        error_message=result.error if not result.success else None,
                        processing_time_seconds=getattr(
                            result, 'processing_time', 0.0)
                    )

                    # Add analysis data if successful
                    if result.success and hasattr(result, 'analysis'):
                        analysis = result.analysis
                        url_result.store_image = analysis.get(
                            'store_image', False)
                        url_result.text_content = analysis.get('text_content')
                        url_result.store_name = analysis.get('store_name')
                        url_result.business_contact = analysis.get(
                            'business_contact')
                        url_result.image_description = analysis.get(
                            'image_description')
                        url_result.raw_analysis = analysis

                    session.add(url_result)

                except Exception as e:
                    logger.error(
                        f"Error storing result for URL {result.url}: {e}")
                    # Continue with other results even if one fails

            session.commit()

    def _update_batch_progress(self, batch_id: str):
        """Update overall batch progress based on completed chunks"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()
            if not batch:
                return

            # Get chunk statistics
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()

            total_processed = sum(
                chunk.processed_count or 0 for chunk in chunks)
            total_successful = sum(
                chunk.successful_count or 0 for chunk in chunks)
            total_failed = sum(chunk.failed_count or 0 for chunk in chunks)

            completed_chunks = sum(
                1 for chunk in chunks if chunk.status == ChunkStatus.COMPLETED)

            # Update batch statistics
            batch.processed_count = total_processed
            batch.successful_count = total_successful
            batch.failed_count = total_failed
            batch.current_chunk = completed_chunks

            # Check if batch is complete
            if completed_chunks == batch.total_chunks:
                if batch.status in [BatchStatus.QUEUED, BatchStatus.PROCESSING]:
                    batch.status = BatchStatus.COMPLETED
                    batch.completed_at = datetime.now()
                    logger.info(
                        f"Batch {batch_id} completed: {total_successful} successful, {total_failed} failed")

            elif total_processed > 0 and batch.status == BatchStatus.QUEUED:
                # Mark as processing once we start processing URLs
                batch.status = BatchStatus.PROCESSING

            session.commit()

    def stop(self):
        """Signal the processor to stop"""
        self.should_stop = True
        if hasattr(self.processor, 'stop_processing'):
            self.processor.stop_processing()


class BackgroundWorker:
    """Background worker that processes jobs from the queue"""

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.chunk_processor = ChunkProcessor(worker_id)
        self.should_stop = False
        self.current_job = None

        logger.info(f"BackgroundWorker {worker_id} initialized")

    async def run(self):
        """Main worker loop"""
        logger.info(f"Worker {self.worker_id} starting...")

        while not self.should_stop:
            try:
                # Get next job from queue
                job = job_queue.dequeue_job(self.worker_id)

                if job is None:
                    # No job available, wait a bit
                    await asyncio.sleep(1)
                    continue

                self.current_job = job

                logger.info(
                    f"Worker {self.worker_id} picked up job {job.job_id}")

                # Process the job
                await self._process_job(job)

                self.current_job = None

            except Exception as e:
                logger.error(f"Worker {self.worker_id} error: {e}")
                if self.current_job:
                    job_queue.fail_job(self.current_job.job_id, str(e))
                    self.current_job = None

                # Wait before retrying
                await asyncio.sleep(5)

        logger.info(f"Worker {self.worker_id} stopped")

    async def _process_job(self, job: Job):
        """Process a specific job"""
        try:
            # Job is already marked as processing by dequeue_job

            if job.job_type == 'chunk_processing':
                # Extract job parameters
                batch_id = job.payload.get('batch_id')
                chunk_id = job.payload.get('chunk_id')
                urls = job.payload.get('urls', [])

                if not all([batch_id, chunk_id, urls]):
                    raise ValueError("Missing required job parameters")

                # Process the chunk
                result = await self.chunk_processor.process_chunk(batch_id, chunk_id, urls)

                # Mark job as completed
                job_queue.complete_job(job.job_id, result)

                logger.info(f"Job {job.job_id} completed successfully")

            else:
                raise ValueError(f"Unknown job type: {job.job_type}")

        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")
            job_queue.fail_job(job.job_id, str(e))
            raise

    def stop(self):
        """Stop the worker"""
        logger.info(f"Stopping worker {self.worker_id}")
        self.should_stop = True
        self.chunk_processor.stop()

        # If currently processing a job, mark it as failed
        if self.current_job:
            job_queue.fail_job(
                self.current_job.job_id,
                "Worker stopped during processing"
            )


class WorkerManager:
    """Manages multiple background workers"""

    def __init__(self, num_workers: int = None):
        self.num_workers = num_workers or config.max_workers
        self.workers: List[BackgroundWorker] = []
        self.worker_tasks: List[asyncio.Task] = []
        self.should_stop = False

        logger.info(
            f"WorkerManager initialized with {self.num_workers} workers")

    async def start_workers(self):
        """Start all background workers"""
        logger.info(f"Starting {self.num_workers} background workers...")

        for i in range(self.num_workers):
            worker_id = f"worker-{i+1}"
            worker = BackgroundWorker(worker_id)
            self.workers.append(worker)

            # Start worker task
            task = asyncio.create_task(worker.run())
            self.worker_tasks.append(task)

        logger.info(f"All {self.num_workers} workers started")

    async def stop_workers(self):
        """Stop all background workers"""
        logger.info("Stopping all background workers...")

        # Signal all workers to stop
        for worker in self.workers:
            worker.stop()

        # Wait for all tasks to complete (with timeout)
        if self.worker_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.worker_tasks, return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Some worker tasks did not complete within timeout")

                # Cancel remaining tasks
                for task in self.worker_tasks:
                    if not task.done():
                        task.cancel()

        self.workers.clear()
        self.worker_tasks.clear()

        logger.info("All workers stopped")

    async def restart_workers(self):
        """Restart all workers"""
        await self.stop_workers()
        await self.start_workers()

    def get_worker_status(self) -> Dict[str, Any]:
        """Get status of all workers"""
        active_workers = sum(
            1 for worker in self.workers if not worker.should_stop)
        processing_jobs = sum(
            1 for worker in self.workers if worker.current_job is not None)

        return {
            'total_workers': len(self.workers),
            'active_workers': active_workers,
            'processing_jobs': processing_jobs,
            'queue_stats': job_queue.get_queue_stats()
        }


# Global worker manager instance
worker_manager = WorkerManager()


async def start_background_workers(num_workers: int = None):
    """Start background workers (convenience function)"""
    global worker_manager

    if num_workers:
        worker_manager = WorkerManager(num_workers)

    await worker_manager.start_workers()


def stop_background_workers():
    """Stop background workers (convenience function)"""
    global worker_manager

    # Run in event loop if available, otherwise create one
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, schedule the coroutine
            task = loop.create_task(worker_manager.stop_workers())
            return task
        else:
            # If loop is not running, run it
            return loop.run_until_complete(worker_manager.stop_workers())
    except RuntimeError:
        # No event loop, create a new one
        return asyncio.run(worker_manager.stop_workers())


def get_worker_status() -> Dict[str, Any]:
    """Get worker status (convenience function)"""
    return worker_manager.get_worker_status()


# Standalone worker process function
async def run_worker_process(worker_id: str = None, num_workers: int = 1):
    """Run worker process (for standalone execution)"""
    if worker_id is None:
        worker_id = f"standalone-{mp.current_process().pid}"

    logger.info(f"Starting standalone worker process: {worker_id}")

    # Setup signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Worker {worker_id} received signal {signum}")
        worker_manager.should_stop = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize worker manager
        global worker_manager
        worker_manager = WorkerManager(num_workers)

        # Start workers
        await worker_manager.start_workers()

        # Wait for stop signal
        while not worker_manager.should_stop:
            await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Worker process error: {e}")
    finally:
        await worker_manager.stop_workers()
        logger.info(f"Worker process {worker_id} finished")


if __name__ == "__main__":
    """Standalone worker process execution"""
    import argparse

    parser = argparse.ArgumentParser(description="Background Worker Process")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of workers")
    parser.add_argument("--worker-id", help="Worker ID")

    args = parser.parse_args()

    # Setup logging for standalone mode
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        asyncio.run(run_worker_process(args.worker_id, args.workers))
    except KeyboardInterrupt:
        logger.info("Worker process interrupted by user")
    except Exception as e:
        logger.error(f"Worker process failed: {e}")
        sys.exit(1)
