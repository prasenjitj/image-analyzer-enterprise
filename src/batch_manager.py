"""
Comprehensive batch management system for enterprise image processing
"""
import csv
import io
import logging
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

from .enterprise_config import config
from .database_models import (
    ProcessingBatch, ProcessingChunk, URLAnalysisResult,
    BatchStatus, ChunkStatus, db_manager
)
from .job_queue import job_queue, enqueue_chunk_processing

logger = logging.getLogger(__name__)


class BatchManager:
    """Manages batch processing lifecycle"""

    def __init__(self):
        self.chunk_size = config.chunk_size
        self.max_concurrent_batches = config.max_concurrent_batches

    # Utility methods to reduce code duplication
    @staticmethod
    def _utc_now():
        """Get current UTC time with timezone info"""
        return datetime.now(timezone.utc)

    @staticmethod
    def _get_batch_by_id(session, batch_id: str) -> Optional[ProcessingBatch]:
        """Get batch by ID with error handling"""
        return session.query(ProcessingBatch).filter_by(batch_id=batch_id).first()

    @staticmethod
    def _validate_batch_exists(session, batch_id: str) -> ProcessingBatch:
        """Get batch by ID and raise error if not found"""
        batch = BatchManager._get_batch_by_id(session, batch_id)
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")
        return batch

    @staticmethod
    def _get_batch_with_chunks(session, batch_id: str):
        """Efficiently get batch with its chunks in one query"""
        from sqlalchemy.orm import joinedload
        return session.query(ProcessingBatch).options(
            joinedload(ProcessingBatch.chunks)
        ).filter_by(batch_id=batch_id).first()

    def create_batch_from_csv(self, csv_content: str, batch_name: str = None,
                              filename: str = None) -> Tuple[str, Dict[str, Any]]:
        """Create a new batch from CSV content with listing data"""

        # Parse CSV content to get listing data
        listings = self._parse_csv_content(csv_content)

        if not listings:
            raise ValueError("No valid listing data found in CSV file")

        # Generate batch name if not provided
        if not batch_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_name = f"Listings_Batch_{timestamp}"

        # Calculate batch parameters
        total_listings = len(listings)
        total_chunks = (total_listings + self.chunk_size -
                        1) // self.chunk_size

        # Create batch record
        with db_manager.get_session() as session:
            batch = ProcessingBatch(
                batch_name=batch_name,
                total_urls=total_listings,
                chunk_size=self.chunk_size,
                total_chunks=total_chunks,
                original_filename=filename,
                file_size_bytes=len(csv_content.encode()),
                processing_config={
                    'chunk_size': self.chunk_size,
                    'max_retries': config.retry_attempts,
                    'timeout': config.request_timeout,
                    'data_type': 'listings'  # Mark this as listings data
                }
            )

            session.add(batch)
            session.commit()
            batch_id = str(batch.batch_id)

        # Create chunks with listing data
        chunks_created = self._create_chunks(batch_id, listings)

        logger.info(
            f"Created batch {batch_id} with {total_listings} listings in {total_chunks} chunks")

        # Return batch information
        batch_info = {
            'batch_id': batch_id,
            'batch_name': batch_name,
            'total_urls': total_listings,  # Keep this name for backward compatibility
            'total_listings': total_listings,
            'total_chunks': total_chunks,
            'chunk_size': self.chunk_size,
            'chunks_created': chunks_created,
            'status': BatchStatus.PENDING.value,
            'estimated_time_hours': self._estimate_processing_time(total_listings)
        }

        return batch_id, batch_info

    def start_batch_processing(self, batch_id: str) -> bool:
        """Start processing a batch"""
        with db_manager.get_session() as session:
            batch = self._validate_batch_exists(session, batch_id)

            if batch.status != BatchStatus.PENDING:
                raise ValueError(f"Batch {batch_id} is not in pending status")

            # Check concurrent batch limit
            active_batches = session.query(ProcessingBatch).filter(
                ProcessingBatch.status.in_(
                    [BatchStatus.QUEUED, BatchStatus.PROCESSING])
            ).count()

            if active_batches >= self.max_concurrent_batches:
                raise ValueError(
                    f"Maximum concurrent batches ({self.max_concurrent_batches}) reached")

            # Update batch status
            batch.status = BatchStatus.QUEUED
            batch.started_at = self._utc_now()
            session.commit()

            # Queue first few chunks for processing
            self._queue_initial_chunks(session, batch_id)

            logger.info(f"Started batch processing for {batch_id}")
            return True

    def pause_batch(self, batch_id: str) -> bool:
        """Pause batch processing"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.status not in [BatchStatus.QUEUED, BatchStatus.PROCESSING]:
                raise ValueError(
                    f"Batch {batch_id} cannot be paused in {batch.status.value} status")

            batch.status = BatchStatus.PAUSED
            batch.paused_at = datetime.now()
            session.commit()

            # TODO: Cancel pending jobs for this batch
            logger.info(f"Paused batch {batch_id}")
            return True

    def resume_batch(self, batch_id: str) -> bool:
        """Resume paused batch processing"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.status != BatchStatus.PAUSED:
                raise ValueError(f"Batch {batch_id} is not paused")

            batch.status = BatchStatus.QUEUED
            batch.paused_at = None
            session.commit()

            # Re-queue pending chunks
            self._queue_pending_chunks(session, batch_id)

            logger.info(f"Resumed batch {batch_id}")
            return True

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel batch processing"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.status in [BatchStatus.COMPLETED, BatchStatus.CANCELLED]:
                raise ValueError(
                    f"Batch {batch_id} is already {batch.status.value}")

            batch.status = BatchStatus.CANCELLED
            batch.completed_at = datetime.now()
            session.commit()

            # TODO: Cancel all pending jobs for this batch
            logger.info(f"Cancelled batch {batch_id}")
            return True

    def retry_batch(self, batch_id: str) -> Dict[str, Any]:
        """Retry a batch by resetting chunks and re-enqueueing for processing"""
        with db_manager.get_session() as session:
            batch = self._validate_batch_exists(session, batch_id)

            # Allow retry from most statuses (except only recently-queued active ones to avoid conflicts)
            # Allow from: PENDING (to start/restart), PAUSED (to resume as retry), PROCESSING (stuck),
            # QUEUED (stuck), FAILED, CANCELLED, or COMPLETED (to reprocess)
            allowed_statuses = [
                BatchStatus.PENDING,
                BatchStatus.PAUSED,
                BatchStatus.PROCESSING,
                BatchStatus.QUEUED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
                BatchStatus.COMPLETED
            ]

            if batch.status not in allowed_statuses:
                return {
                    'success': False,
                    'error': f"Batch cannot be retried from {batch.status.value} status",
                    'id': str(batch_id)
                }

            # If batch is COMPLETED but all chunks completed, still allow retry
            if batch.status == BatchStatus.COMPLETED:
                # Allow user to re-run a completed batch
                pass

            # Reset all chunks to PENDING
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            reset_chunks = 0

            for chunk in chunks:
                chunk.status = ChunkStatus.PENDING
                chunk.started_at = None
                chunk.completed_at = None
                chunk.processed_count = 0
                chunk.successful_count = 0
                chunk.failed_count = 0
                chunk.processing_time_seconds = None
                chunk.worker_id = None
                reset_chunks += 1

            # Reset batch progress counters
            old_status = batch.status
            batch.status = BatchStatus.QUEUED
            batch.started_at = self._utc_now()
            batch.processed_count = 0
            batch.successful_count = 0
            batch.failed_count = 0
            batch.current_chunk = 0

            session.commit()

            # Queue initial chunks for processing
            self._queue_initial_chunks(session, batch_id)

            logger.info(
                f"Retried batch {batch_id}: reset {reset_chunks} chunks, status transitioned from {old_status} to QUEUED")

            return {
                'success': True,
                'id': str(batch_id),
                'status': 'retry_enqueued',
                'message': f"Batch queued for retry. Reset {reset_chunks} chunks.",
                'reset_chunks': reset_chunks,
                'previous_status': old_status.value
            }

    def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """Get comprehensive status of a batch"""
        try:
            logger.info(f"Getting batch status for batch_id: {batch_id}")

            with db_manager.get_session() as session:
                # Get the batch
                batch = self._validate_batch_exists(session, batch_id)

                logger.info(
                    f"Found batch: {batch.batch_id}, status: {batch.status}")

                # Get chunk statistics
                logger.info("Getting chunk statistics...")
                chunk_stats = self._get_chunk_statistics(session, batch_id)
                logger.info(f"Chunk statistics: {chunk_stats}")

                # Calculate processing rate
                logger.info("Calculating processing rate...")
                processing_rate = self._calculate_processing_rate(batch)
                logger.info(f"Processing rate: {processing_rate}")

                # Calculate ETA
                logger.info("Calculating ETA...")
                eta = self._calculate_eta(batch, processing_rate)
                logger.info(f"ETA: {eta}")

                # Get recent errors
                logger.info("Getting recent errors...")
                recent_errors = self._get_recent_errors(session, batch_id)
                logger.info(f"Recent errors count: {len(recent_errors)}")

                # Calculate timing information
                elapsed_minutes = 0
                remaining_minutes = None
                started_at_iso = None
                completed_at_iso = None

                if hasattr(batch, 'started_at') and batch.started_at:
                    started_at_iso = batch.started_at.isoformat()

                    # If batch has completed, elapsed time should be frozen to
                    # completed_at - started_at. Otherwise compute elapsed up
                    # to now. This prevents the UI from continuing to increment
                    # processing time after completion.
                    if hasattr(batch, 'completed_at') and batch.completed_at:
                        try:
                            elapsed_minutes = (
                                batch.completed_at - batch.started_at).total_seconds() / 60
                        except Exception:
                            # Fallback to UTC now if timezone issues arise
                            elapsed_minutes = (
                                self._utc_now() - batch.started_at).total_seconds() / 60
                    else:
                        elapsed_minutes = (
                            self._utc_now() - batch.started_at).total_seconds() / 60

                    # Only compute remaining time while batch is actively running
                    if not (hasattr(batch, 'completed_at') and batch.completed_at) and processing_rate > 0:
                        remaining_urls = batch.total_urls - batch.processed_count
                        remaining_minutes = remaining_urls / processing_rate

                if hasattr(batch, 'completed_at') and batch.completed_at:
                    completed_at_iso = batch.completed_at.isoformat()

                # Calculate current chunk for progress display
                current_chunk = 0
                if chunk_stats and chunk_stats.get('completed', 0) > 0:
                    current_chunk = chunk_stats.get('completed', 0)
                elif chunk_stats and chunk_stats.get('processing', 0) > 0:
                    current_chunk = chunk_stats.get('completed', 0) + 1

                # Calculate performance metrics
                success_rate = 0
                average_time_per_url = 0
                if batch.processed_count > 0:
                    success_rate = (batch.successful_count / batch.processed_count) * 100 if hasattr(
                        batch, 'successful_count') and batch.successful_count else 0
                    if elapsed_minutes > 0:
                        average_time_per_url = (
                            elapsed_minutes * 60) / batch.processed_count  # seconds per URL

                status = {
                    'batch_id': str(batch.batch_id),  # Convert UUID to string
                    'status': batch.status.value,  # Convert enum to string
                    'created_at': batch.created_at.isoformat(),
                    'updated_at': batch.created_at.isoformat(),  # Using created_at as fallback
                    'total_files': batch.total_urls,
                    'processed_files': batch.processed_count,
                    'progress_percentage': round((batch.processed_count / batch.total_urls) * 100, 2) if batch.total_urls > 0 else 0,
                    'chunk_statistics': chunk_stats,
                    'processing_rate': processing_rate,
                    'estimated_completion': eta.isoformat() if eta else None,
                    # Limit to 10 most recent
                    'recent_errors': recent_errors[:10],
                    'batch_info': {
                        'batch_name': batch.batch_name,
                        'status': batch.status.value,
                        'is_active': batch.is_active,
                        # Convert UUID to string
                        'batch_id': str(batch.batch_id),
                        'total_urls': batch.total_urls,
                        'processed_count': batch.processed_count,
                        'created_at': batch.created_at.isoformat()
                    },
                    'timing': {
                        'created_at': batch.created_at.isoformat(),
                        'started_at': started_at_iso,
                        'completed_at': completed_at_iso,
                        'elapsed_time_minutes': elapsed_minutes,
                        'estimated_completion': eta.isoformat() if eta else None,
                        'remaining_time_minutes': remaining_minutes
                    },
                    'progress': {
                        'progress_percentage': round((batch.processed_count / batch.total_urls) * 100, 2) if batch.total_urls > 0 else 0,
                        'total_urls': batch.total_urls,
                        'processed_count': batch.processed_count,
                        'successful_count': batch.successful_count if hasattr(batch, 'successful_count') else 0,
                        'failed_count': batch.failed_count if hasattr(batch, 'failed_count') else 0,
                        'current_chunk': current_chunk,
                        'total_chunks': batch.total_chunks if hasattr(batch, 'total_chunks') else chunk_stats.get('total', 0)
                    },
                    'performance': {
                        'processing_rate_per_minute': processing_rate,
                        'success_rate_percentage': success_rate,
                        'average_time_per_url': average_time_per_url
                    }
                }

                logger.info(
                    f"Successfully compiled batch status for: {batch_id}")
                return status

        except Exception as e:
            logger.error(f"Error in get_batch_status for {batch_id}: {e}")
            logger.exception("Full exception details:")
            raise

    def list_batches(self, limit: int = 50, status_filter: str = None, include_soft_deleted: bool = False) -> List[Dict[str, Any]]:
        """List all batches with optional filtering"""
        with db_manager.get_session() as session:
            query = session.query(ProcessingBatch)

            # Exclude soft deleted batches unless explicitly requested
            if not include_soft_deleted:
                query = query.filter(
                    ~((ProcessingBatch.status == BatchStatus.CANCELLED) &
                      (ProcessingBatch.error_message.like('%Soft deleted%')))
                )

            if status_filter:
                try:
                    status_enum = BatchStatus(status_filter)
                    query = query.filter(ProcessingBatch.status == status_enum)
                except ValueError:
                    raise ValueError(f"Invalid status filter: {status_filter}")

            batches = query.order_by(
                ProcessingBatch.created_at.desc()).limit(limit).all()

            return [batch.to_dict() for batch in batches]

    def delete_batch(self, batch_id: str, force: bool = False) -> bool:
        """Delete a batch and all associated data"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            if batch.is_active and not force:
                raise ValueError(
                    f"Cannot delete active batch {batch_id}. Use force=True to override.")

            # Delete associated data in correct order to avoid foreign key violations
            # 1. Delete URL analysis results first (references chunks)
            session.query(URLAnalysisResult).filter_by(
                batch_id=batch_id).delete()
            # 2. Delete chunks (referenced by results)
            session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).delete()
            # 3. Delete the batch itself
            session.delete(batch)
            session.commit()

            logger.info(f"Deleted batch {batch_id}")
            return True

    def force_start_batch(self, batch_id: str, skip_validation: bool = False) -> Dict[str, Any]:
        """Force start a batch regardless of current state"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Store original state for logging
            original_status = batch.status

            if not skip_validation:
                # Basic safety checks
                if batch.status == BatchStatus.COMPLETED:
                    raise ValueError(
                        "Cannot force start a completed batch. Use clone instead.")

            # Force set to PENDING then start normally
            batch.status = BatchStatus.PENDING
            batch.started_at = None
            batch.paused_at = None
            batch.error_message = None

            # Reset chunk statuses to PENDING
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            for chunk in chunks:
                if chunk.status != ChunkStatus.COMPLETED:
                    chunk.status = ChunkStatus.PENDING
                    chunk.started_at = None
                    chunk.error_message = None

            session.commit()

            # Now start normally
            self.start_batch_processing(batch_id)

            logger.info(
                f"Force started batch {batch_id} from {original_status.value}")

            return {
                'success': True,
                'batch_id': batch_id,
                'original_status': original_status.value,
                'new_status': 'PROCESSING',
                'chunks_reset': len([c for c in chunks if c.status != ChunkStatus.COMPLETED]),
                'message': f'Successfully force started batch from {original_status.value}'
            }

    def soft_delete_batch(self, batch_id: str, retention_days: int = 30) -> Dict[str, Any]:
        """Soft delete a batch (mark as deleted but preserve data)"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Mark as soft deleted
            batch.status = BatchStatus.CANCELLED
            batch.completed_at = datetime.now()
            batch.error_message = f'Soft deleted on {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} (retention: {retention_days} days)'

            session.commit()

            logger.info(f"Soft deleted batch {batch_id}")

            return {
                'success': True,
                'batch_id': batch_id,
                'retention_days': retention_days,
                'deletion_date': datetime.now().isoformat(),
                'message': f'Batch soft deleted with {retention_days} day retention'
            }

    def clone_batch(self, batch_id: str, new_name: str, copy_results: bool = False) -> Dict[str, Any]:
        """Clone a batch with optional result copying"""
        with db_manager.get_session() as session:
            original_batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not original_batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Create new batch with same configuration
            new_batch = ProcessingBatch(
                batch_name=new_name,
                total_urls=original_batch.total_urls,
                chunk_size=original_batch.chunk_size,
                total_chunks=original_batch.total_chunks,
                status=BatchStatus.PENDING,
                processing_config=original_batch.processing_config
            )
            session.add(new_batch)
            session.flush()

            # Clone chunks
            original_chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()

            chunks_created = 0
            for chunk in original_chunks:
                new_chunk = ProcessingChunk(
                    batch_id=str(new_batch.batch_id),  # Convert UUID to string
                    chunk_number=chunk.chunk_number,
                    urls=chunk.urls,
                    url_count=chunk.url_count,
                    status=ChunkStatus.PENDING
                )
                session.add(new_chunk)
                chunks_created += 1

            # Optionally copy results
            results_copied = 0
            if copy_results:
                original_results = session.query(URLAnalysisResult).filter_by(
                    batch_id=batch_id).all()

                for result in original_results:
                    # Find corresponding chunk in new batch
                    new_chunk = session.query(ProcessingChunk).filter_by(
                        # Convert UUID to string
                        batch_id=str(new_batch.batch_id),
                        chunk_number=result.chunk_id  # This needs refinement
                    ).first()

                    if new_chunk:
                        new_result = URLAnalysisResult(
                            # Convert UUID to string
                            batch_id=str(new_batch.batch_id),
                            chunk_id=new_chunk.chunk_id,
                            url=result.url,
                            url_hash=result.url_hash,
                            success=result.success,
                            store_image=result.store_image,
                            text_content=result.text_content,
                            store_name=result.store_name,
                            business_contact=result.business_contact,
                            image_description=result.image_description,
                            error_message=result.error_message,
                            processing_time_seconds=result.processing_time_seconds
                        )
                        session.add(new_result)
                        results_copied += 1

            session.commit()

            logger.info(f"Cloned batch {batch_id} to {new_batch.batch_id}")

            return {
                'success': True,
                'original_batch_id': batch_id,
                'new_batch_id': str(new_batch.batch_id),
                'new_batch_name': new_name,
                'chunks_created': chunks_created,
                'results_copied': results_copied,
                'message': f'Successfully cloned batch to {new_name}'
            }

    def get_batch_details(self, batch_id: str) -> Dict[str, Any]:
        """Get detailed batch information"""
        try:
            with db_manager.get_session() as session:
                batch = self._validate_batch_exists(session, batch_id)

                # Get chunk statistics
                chunks = session.query(ProcessingChunk).filter_by(
                    batch_id=batch.batch_id).all()
                chunk_stats = {
                    'total': len(chunks),
                    'completed': len([c for c in chunks if c.status == ChunkStatus.COMPLETED]),
                    'processing': len([c for c in chunks if c.status == ChunkStatus.PROCESSING]),
                    'pending': len([c for c in chunks if c.status == ChunkStatus.PENDING])
                }

                # Get recent results
                recent_results = session.query(URLAnalysisResult).filter_by(
                    batch_id=batch.batch_id
                ).order_by(URLAnalysisResult.result_id.desc()).limit(10).all()

                return {
                    'batch_id': str(batch.batch_id),
                    'batch_name': batch.batch_name,
                    'status': batch.status.value,
                    'description': getattr(batch, 'description', ''),
                    'created_at': batch.created_at.isoformat(),
                    'total_urls': batch.total_urls,
                    'processed_count': batch.processed_count,
                    'successful_count': getattr(batch, 'successful_count', 0),
                    'progress_percentage': round((batch.processed_count / batch.total_urls) * 100, 2) if batch.total_urls > 0 else 0,
                    'chunk_statistics': chunk_stats,
                    'recent_results': [
                        {
                            'result_id': str(result.result_id),
                            'url': result.url,
                            'success': result.success,
                            'store_name': result.store_name,
                            'store_front_match_score': getattr(result, 'store_front_match_score', None),
                            'store_front_match': getattr(result, 'store_front_match', None),
                            'error_message': result.error_message
                        } for result in recent_results
                    ]
                }
        except Exception as e:
            logger.error(f"Error getting batch details for {batch_id}: {e}")
            return None

    def get_batch_results(self, batch_id: str, status_filter: str = None) -> List[Dict[str, Any]]:
        """Get batch results with optional status filtering, including listing data"""
        try:
            with db_manager.get_session() as session:
                # First check if batch exists
                batch = session.query(ProcessingBatch).filter_by(
                    batch_id=batch_id).first()
                if not batch:
                    return None

                # Build query for results
                query = session.query(
                    URLAnalysisResult).filter_by(batch_id=batch_id)

                # Apply status filter if provided
                if status_filter:
                    if status_filter.lower() == 'success':
                        query = query.filter(URLAnalysisResult.success == True)
                    elif status_filter.lower() == 'failed':
                        query = query.filter(
                            URLAnalysisResult.success == False)

                results = query.order_by(
                    URLAnalysisResult.created_at.desc()).all()

                return [
                    {
                        'id': str(result.result_id),
                        'url': result.url,
                        # Listing data
                        'serial_number': result.serial_number,
                        'business_name': result.business_name,
                        'input_phone_number': result.input_phone_number,
                        'storefront_photo_url': result.storefront_photo_url,
                        # Analysis results
                        'success': result.success,
                        'store_image': result.store_image,
                        'store_name': result.store_name,
                        'business_contact': result.business_contact,
                        'phone_number': result.phone_number,
                        'image_description': result.image_description,
                        # Truncate for API
                        'text_content': result.text_content[:500] if result.text_content else None,
                        'error_message': result.error_message,
                        'store_front_match_score': getattr(result, 'store_front_match_score', None),
                        'store_front_match': getattr(result, 'store_front_match', None),
                        'phone_match_score': getattr(result, 'phone_match_score', None),
                        'phone_match': getattr(result, 'phone_match', None),
                        'processing_time_seconds': result.processing_time_seconds
                    } for result in results
                ]
        except Exception as e:
            logger.error(f"Error getting batch results for {batch_id}: {e}")
            return []

    def get_batch_health_score(self, batch_id: str) -> Dict[str, Any]:
        """Calculate health score and diagnostics for a batch"""
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Get chunks and results
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            results = session.query(URLAnalysisResult).filter_by(
                batch_id=batch_id).all()

            # Calculate metrics
            total_chunks = len(chunks)
            completed_chunks = len(
                [c for c in chunks if c.status == ChunkStatus.COMPLETED])
            failed_chunks = len(
                [c for c in chunks if c.status == ChunkStatus.FAILED])

            total_urls = batch.total_urls
            processed_urls = len(results)
            successful_urls = len([r for r in results if r.success])

            # Calculate health score (0-100)
            health_score = 100

            # Penalize for failures
            if total_chunks > 0:
                failure_rate = failed_chunks / total_chunks
                # Up to 30 points off for failures
                health_score -= (failure_rate * 30)

            # Penalize for being stuck
            if batch.status in [BatchStatus.PROCESSING, BatchStatus.QUEUED]:
                now = datetime.now(
                    timezone.utc) if batch.created_at.tzinfo else datetime.now()
                age_hours = (now - batch.created_at).total_seconds() / 3600
                if age_hours > 24:
                    # Penalize old processing batches
                    health_score -= min(20, age_hours - 24)

            # Penalize for low success rate
            if processed_urls > 0:
                success_rate = successful_urls / processed_urls
                if success_rate < 0.8:
                    health_score -= (0.8 - success_rate) * \
                        50  # Penalize low success rate

            health_score = max(0, min(100, health_score))  # Clamp to 0-100

            # Determine issues
            issues = []
            recommendations = []

            if failed_chunks > 0:
                issues.append(f"{failed_chunks} failed chunks")
                recommendations.append("Consider resetting failed chunks")

            if batch.status == BatchStatus.PROCESSING:
                now = datetime.now(
                    timezone.utc) if batch.created_at.tzinfo else datetime.now()
                age_hours = (now - batch.created_at).total_seconds() / 3600
                if age_hours > 24:
                    issues.append(f"Processing for {age_hours:.1f} hours")
                    recommendations.append(
                        "Consider force restart or cancellation")

            if processed_urls > 0:
                success_rate = successful_urls / processed_urls
                if success_rate < 0.5:
                    issues.append(f"Low success rate ({success_rate:.1%})")
                    recommendations.append(
                        "Check API configuration and URL quality")

            return {
                'success': True,
                'batch_id': batch_id,
                'health_score': round(health_score, 1),
                'status': batch.status.value,
                'metrics': {
                    'total_chunks': total_chunks,
                    'completed_chunks': completed_chunks,
                    'failed_chunks': failed_chunks,
                    'total_urls': total_urls,
                    'processed_urls': processed_urls,
                    'successful_urls': successful_urls,
                    'success_rate': round(successful_urls / max(processed_urls, 1), 3),
                    'completion_rate': round(completed_chunks / max(total_chunks, 1), 3)
                },
                'issues': issues,
                'recommendations': recommendations,
                'age_hours': ((datetime.now(timezone.utc) if batch.created_at.tzinfo else datetime.now()) - batch.created_at).total_seconds() / 3600
            }

    def analyze_batch_errors(self, batch_id: str) -> Dict[str, Any]:
        """Analyze error patterns in a batch"""
        with db_manager.get_session() as session:
            # Get failed results
            failed_results = session.query(URLAnalysisResult).filter_by(
                batch_id=batch_id,
                success=False
            ).all()

            # Get failed chunks
            failed_chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id,
                status=ChunkStatus.FAILED
            ).all()

            # Analyze error patterns
            error_patterns = {}
            chunk_errors = {}

            for result in failed_results:
                if result.error_message:
                    error_type = result.error_message.split(
                        ':')[0]  # Get error type
                    error_patterns[error_type] = error_patterns.get(
                        error_type, 0) + 1

            for chunk in failed_chunks:
                if chunk.error_message:
                    error_type = chunk.error_message.split(':')[0]
                    chunk_errors[error_type] = chunk_errors.get(
                        error_type, 0) + 1

            # Generate recommendations
            recommendations = []
            if 'API key not valid' in str(error_patterns):
                recommendations.append("Check API key configuration")
            if 'timeout' in str(error_patterns).lower():
                recommendations.append("Consider increasing timeout settings")
            if len(failed_results) > len(failed_results) * 0.5:
                recommendations.append("High failure rate - check URL quality")

            return {
                'success': True,
                'batch_id': batch_id,
                'total_failed_urls': len(failed_results),
                'total_failed_chunks': len(failed_chunks),
                'url_error_patterns': error_patterns,
                'chunk_error_patterns': chunk_errors,
                'recommendations': recommendations
            }

    def _parse_csv_content(self, csv_content: str) -> List[Dict[str, str]]:
        """Parse CSV content and extract listing data"""
        listings = []

        try:
            csv_reader = csv.DictReader(io.StringIO(csv_content))

            for row_num, row in enumerate(csv_reader, start=1):
                # Extract listing data with multiple possible column name variants
                listing_data = {}

                # Serial Number
                serial_number = None
                for column in ['Serial No.', 'Serial No', 'serial_no', 'serial_number', 'id', 'ID']:
                    if column in row and row[column]:
                        serial_number = row[column].strip()
                        break

                # Business Name
                business_name = None
                for column in ['Business Name', 'business_name', 'name', 'store_name', 'company']:
                    if column in row and row[column]:
                        business_name = row[column].strip()
                        break

                # Phone Number
                phone_number = None
                for column in ['Phone Number', 'phone_number', 'phone', 'contact', 'mobile']:
                    if column in row and row[column]:
                        phone_number = row[column].strip()
                        break

                # StoreFront Photo URL
                storefront_url = None
                for column in ['StoreFront Photo URL', 'storefront_photo_url', 'photo_url', 'image_url', 'url', 'URL']:
                    if column in row and row[column]:
                        storefront_url = row[column].strip()
                        break

                # Validate required fields
                if not storefront_url or not (storefront_url.startswith('http://') or storefront_url.startswith('https://')):
                    logger.warning(
                        f"Row {row_num}: Invalid or missing StoreFront Photo URL")
                    continue

                # Create listing entry
                listing_data = {
                    'serial_number': serial_number or str(row_num),
                    'business_name': business_name or 'Unknown Business',
                    'phone_number': phone_number or '',
                    'storefront_photo_url': storefront_url,
                    'row_number': row_num
                }

                listings.append(listing_data)

        except Exception as e:
            logger.error(f"Error parsing CSV content: {e}")
            raise ValueError(f"Invalid CSV format: {e}")

        if not listings:
            raise ValueError(
                "No valid listing data found in CSV. Required columns: StoreFront Photo URL")

        # Remove duplicates based on storefront_photo_url while preserving order
        seen = set()
        unique_listings = []
        for listing in listings:
            url = listing['storefront_photo_url']
            if url not in seen:
                seen.add(url)
                unique_listings.append(listing)

        logger.info(f"Parsed {len(unique_listings)} unique listings from CSV")
        return unique_listings

    def _create_chunks(self, batch_id: str, listings: List[Dict[str, str]]) -> int:
        """Create chunks for a batch with listing data"""
        chunks_created = 0

        with db_manager.get_session() as session:
            for i in range(0, len(listings), self.chunk_size):
                chunk_listings = listings[i:i + self.chunk_size]
                chunk_number = (i // self.chunk_size) + 1

                # Store listing data in the chunk's urls field (as JSON)
                # This maintains backward compatibility while storing richer data
                chunk = ProcessingChunk(
                    batch_id=batch_id,
                    chunk_number=chunk_number,
                    urls=chunk_listings,  # Store full listing data as JSON
                    url_count=len(chunk_listings)
                )

                session.add(chunk)
                chunks_created += 1

            session.commit()

        return chunks_created

    def _queue_initial_chunks(self, session, batch_id: str, max_chunks: int = 3):
        """Queue initial chunks for processing"""
        chunks = session.query(ProcessingChunk).filter_by(
            batch_id=batch_id,
            status=ChunkStatus.PENDING
        ).order_by(ProcessingChunk.chunk_number).limit(max_chunks).all()

        for chunk in chunks:
            chunk.status = ChunkStatus.PROCESSING  # Mark as queued for processing
            chunk.started_at = self._utc_now()  # Set start time
            job_id = enqueue_chunk_processing(
                str(batch_id),
                str(chunk.chunk_id),
                chunk.urls  # This now contains listing data
            )
            logger.info(
                f"Queued chunk {chunk.chunk_number} for batch {batch_id} (job: {job_id})")

        session.commit()

    def _queue_pending_chunks(self, session, batch_id: str):
        """Queue all pending chunks for processing"""
        chunks = session.query(ProcessingChunk).filter_by(
            batch_id=batch_id,
            status=ChunkStatus.PENDING
        ).all()

        for chunk in chunks:
            enqueue_chunk_processing(
                str(batch_id),
                str(chunk.chunk_id),
                chunk.urls  # This now contains listing data
            )

        logger.info(
            f"Queued {len(chunks)} pending chunks for batch {batch_id}")

    def _get_chunk_statistics(self, session, batch_id: str) -> Dict[str, int]:
        """Get chunk processing statistics"""
        chunks = session.query(ProcessingChunk).filter_by(
            batch_id=batch_id).all()

        stats = {
            'total': len(chunks),
            'pending': 0,
            'processing': 0,
            'completed': 0,
            'failed': 0,
            'retrying': 0
        }

        for chunk in chunks:
            status_value = chunk.status.value
            # Safely increment status count, defaulting to 0 for unknown statuses
            if status_value in stats:
                stats[status_value] += 1
            else:
                # Log unknown status but don't crash
                logger.warning(
                    f"Unknown chunk status encountered: {status_value}")
                # Create a new entry for this status
                stats[status_value] = 1

        return stats

    def _calculate_processing_rate(self, batch: ProcessingBatch) -> float:
        """Calculate current processing rate (URLs per minute)"""
        if not batch.started_at or batch.processed_count == 0:
            return 0.0

        elapsed_minutes = (
            self._utc_now() - batch.started_at).total_seconds() / 60
        if elapsed_minutes < 1:
            return 0.0

        return batch.processed_count / elapsed_minutes

    def _calculate_eta(self, batch: ProcessingBatch, processing_rate: float) -> Optional[datetime]:
        """Calculate estimated completion time"""
        if processing_rate <= 0:
            return None

        remaining_urls = batch.total_urls - batch.processed_count
        remaining_minutes = remaining_urls / processing_rate

        return self._utc_now() + timedelta(minutes=remaining_minutes)

    def _get_elapsed_time(self, batch: ProcessingBatch) -> float:
        """Get elapsed processing time in minutes"""
        if not batch.started_at:
            return 0.0

        return (self._utc_now() - batch.started_at).total_seconds() / 60

    def _get_remaining_time(self, batch: ProcessingBatch, processing_rate: float) -> Optional[float]:
        """Get remaining processing time in minutes"""
        if processing_rate <= 0:
            return None

        remaining_urls = batch.total_urls - batch.processed_count
        return remaining_urls / processing_rate

    def _get_average_processing_time(self, session, batch_id: str) -> float:
        """Get average processing time per URL"""
        results = session.query(URLAnalysisResult).filter_by(
            batch_id=batch_id).all()

        if not results:
            return 0.0

        total_time = sum(
            r.processing_time_seconds for r in results if r.processing_time_seconds)
        return total_time / len(results) if results else 0.0

    def _get_recent_errors(self, session, batch_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent error messages"""
        results = session.query(URLAnalysisResult).filter(
            URLAnalysisResult.batch_id == batch_id,
            URLAnalysisResult.success == False,
            URLAnalysisResult.error_message.isnot(None)
        ).order_by(URLAnalysisResult.created_at.desc()).limit(limit).all()

        return [
            {
                'url': result.url,
                'error_message': result.error_message,
                'created_at': result.created_at.isoformat()
            }
            for result in results
        ]

    def _estimate_processing_time(self, total_urls: int) -> float:
        """Estimate processing time in hours"""
        # Base estimate: 60 URLs per minute with single API key
        api_keys_count = len(
            config.api_keys_list) if config.api_keys_list else 1
        urls_per_hour = 60 * 60 / api_keys_count
        return total_urls / urls_per_hour

    def get_batch_summary_stats(self) -> Dict[str, Any]:
        """Get overall batch processing statistics"""
        with db_manager.get_session() as session:
            # Count only completed/processed batches
            total_batches = session.query(ProcessingBatch).filter_by(
                status=BatchStatus.COMPLETED
            ).count()
            active_batches = session.query(ProcessingBatch).filter(
                ProcessingBatch.status.in_(
                    [BatchStatus.PENDING, BatchStatus.QUEUED, BatchStatus.PROCESSING])
            ).count()
            completed_batches = total_batches  # Same as total_batches now

            # Get processing statistics
            total_urls_processed = session.query(URLAnalysisResult).count()
            successful_urls = session.query(
                URLAnalysisResult).filter_by(success=True).count()

            return {
                'total_batches': total_batches,
                'active_batches': active_batches,
                'completed_batches': completed_batches,
                'total_urls_processed': total_urls_processed,
                'successful_urls': successful_urls,
                'overall_success_rate': (successful_urls / max(total_urls_processed, 1)) * 100,
                'queue_stats': job_queue.get_queue_stats()
            }

    def reset_stuck_batch(self, batch_id: str, force: bool = False) -> Dict[str, Any]:
        """Reset a stuck batch back to PENDING status"""
        with db_manager.get_session() as session:
            batch = self._validate_batch_exists(session, batch_id)

            # Only allow reset if batch is stuck
            if not force and batch.status not in [BatchStatus.QUEUED, BatchStatus.PROCESSING, BatchStatus.PENDING]:
                return {
                    'success': False,
                    'error': f"Batch is in {batch.status} status. Use force=True to reset anyway."
                }

            # Reset batch status
            old_status = batch.status
            batch.status = BatchStatus.PENDING
            batch.started_at = None
            batch.completed_at = None
            batch.processed_count = 0
            batch.successful_count = 0
            batch.failed_count = 0
            batch.current_chunk = 0

            # Reset all chunks to PENDING
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            reset_chunks = 0

            for chunk in chunks:
                chunk.status = ChunkStatus.PENDING
                chunk.started_at = None
                chunk.completed_at = None
                chunk.processed_count = 0
                chunk.successful_count = 0
                chunk.failed_count = 0
                chunk.processing_time_seconds = None
                chunk.worker_id = None
                reset_chunks += 1

            session.commit()

            logger.info(
                f"Reset batch {batch_id} from {old_status} to PENDING ({reset_chunks} chunks reset)")

            return {
                'success': True,
                'message': f"Reset batch from {old_status} to PENDING",
                'reset_chunks': reset_chunks,
                'batch_status': 'pending'
            }


# Global batch manager instance
batch_manager = BatchManager()


# Job handler functions for the job queue system
def process_chunk_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Job handler for processing chunks with listing data"""
    try:
        batch_id = payload.get('batch_id')
        chunk_id = payload.get('chunk_id')
        # 'urls' field now contains listing data
        listings = payload.get('urls', [])

        if not all([batch_id, chunk_id, listings]):
            raise ValueError(
                "Missing required parameters: batch_id, chunk_id, or listings")

        logger.info(
            f"Processing chunk {chunk_id} for batch {batch_id} with {len(listings)} listings")

        # Import processor here to avoid circular imports
        from .processor import image_processor
        from .cache import get_cache
        import asyncio

        # Get cache instance
        cache = get_cache()

        # Extract storefront URLs for processing and caching
        storefront_urls = []
        listings_by_url = {}  # Map URLs to their listing data

        for listing in listings:
            if isinstance(listing, dict):
                url = listing.get('storefront_photo_url')
                if url:
                    storefront_urls.append(url)
                    listings_by_url[url] = listing

        # Filter URLs that need processing (not in cache)
        urls_to_process = cache.batch_get_missing_urls(storefront_urls)
        cached_results = cache.batch_get_analyses(storefront_urls)

        logger.info(
            f"Chunk {chunk_id}: {len(cached_results)} URLs from cache, {len(urls_to_process)} to process")

        # Process new URLs
        new_results = []
        if urls_to_process:
            # Create event loop if not exists
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Process URLs
            new_results = loop.run_until_complete(
                image_processor.process_batch(urls_to_process)
            )

            # Cache new results
            for result in new_results:
                if result.success and result.analysis:
                    cache.set_analysis(result.url, result.analysis)

        # Combine results with listing data
        all_results = []

        # Add cached results with listing data
        for url in storefront_urls:
            if url in cached_results:
                # Create result object from cached data
                from .processor import ProcessingResult
                cached_result = ProcessingResult(
                    url=url,
                    success=True,
                    analysis=cached_results[url],
                    processing_time=0.0,
                    cache_hit=True
                )
                # Attach listing data
                if url in listings_by_url:
                    cached_result.listing_data = listings_by_url[url]
                all_results.append(cached_result)

        # Add new results with listing data
        for result in new_results:
            if result.url in listings_by_url:
                result.listing_data = listings_by_url[result.url]
            all_results.append(result)

        # Store results in database with listing data
        _store_chunk_results_in_db(batch_id, chunk_id, all_results)

        # Update chunk status
        _update_chunk_completion(chunk_id, all_results)

        # Update batch progress
        _update_batch_progress(batch_id)

        # Calculate statistics
        successful_count = sum(1 for r in all_results if r.success)
        failed_count = len(all_results) - successful_count
        cache_hits = sum(
            1 for r in all_results if getattr(r, 'cache_hit', False))

        result = {
            'chunk_id': chunk_id,
            'batch_id': batch_id,
            'total_urls': len(listings),  # Fixed to use listings
            'total_listings': len(listings),
            'processed_count': len(all_results),
            'successful_count': successful_count,
            'failed_count': failed_count,
            'cache_hits': cache_hits,
            'new_processed': len(new_results)
        }

        logger.info(
            f"Chunk {chunk_id} completed: {successful_count} successful, {failed_count} failed, {cache_hits} from cache")
        return result

    except Exception as e:
        logger.error(
            f"Error processing chunk {payload.get('chunk_id', 'unknown')}: {e}")
        # Update chunk as failed
        if payload.get('chunk_id'):
            _update_chunk_failed(payload['chunk_id'], str(e))
        raise


def finalize_batch_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Job handler for finalizing batches"""
    try:
        batch_id = payload.get('batch_id')
        if not batch_id:
            raise ValueError("Missing batch_id parameter")

        logger.info(f"Finalizing batch {batch_id}")

        with db_manager.get_session() as session:
            # Get batch
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()
            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Calculate final statistics
            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            completed_chunks = [
                c for c in chunks if c.status == ChunkStatus.COMPLETED]

            if len(completed_chunks) == batch.total_chunks:
                # All chunks completed
                batch.status = BatchStatus.COMPLETED
                batch.completed_at = datetime.now()

                # Calculate final statistics
                total_successful = sum(c.successful_count or 0 for c in chunks)
                total_failed = sum(c.failed_count or 0 for c in chunks)
                total_processed = sum(c.processed_count or 0 for c in chunks)

                batch.successful_count = total_successful
                batch.failed_count = total_failed
                batch.processed_count = total_processed

                # Calculate success rate
                if total_processed > 0:
                    batch.success_rate = (
                        total_successful / total_processed) * 100

                session.commit()

                logger.info(
                    f"Batch {batch_id} finalized: {total_successful} successful, {total_failed} failed")

                return {
                    'batch_id': batch_id,
                    'status': 'completed',
                    'total_processed': total_processed,
                    'successful_count': total_successful,
                    'failed_count': total_failed,
                    'success_rate': batch.success_rate
                }
            else:
                # Not all chunks completed yet
                logger.warning(
                    f"Batch {batch_id} finalization called but not all chunks completed")
                return {
                    'batch_id': batch_id,
                    'status': 'pending',
                    'completed_chunks': len(completed_chunks),
                    'total_chunks': batch.total_chunks
                }

    except Exception as e:
        logger.error(
            f"Error finalizing batch {payload.get('batch_id', 'unknown')}: {e}")
        raise


def _store_chunk_results_in_db(batch_id: str, chunk_id: str, results: List[Any]):
    """Store chunk processing results in database with listing data"""
    with db_manager.get_session() as session:
        for result in results:
            # Generate URL hash for deduplication
            url_hash = hashlib.sha256(result.url.encode()).hexdigest()

            # Create URLAnalysisResult record
            url_result = URLAnalysisResult(
                batch_id=batch_id,
                chunk_id=chunk_id,
                url=result.url,
                url_hash=url_hash,
                success=result.success,
                error_message=result.error if not result.success else None,
                processing_time_seconds=getattr(
                    result, 'processing_time', 0.0),
                cache_hit=getattr(result, 'cache_hit', False)
            )

            # Add listing data if available
            if hasattr(result, 'listing_data') and result.listing_data:
                listing = result.listing_data
                url_result.serial_number = listing.get('serial_number')
                url_result.business_name = listing.get('business_name')
                url_result.input_phone_number = listing.get('phone_number')
                url_result.storefront_photo_url = listing.get(
                    'storefront_photo_url')

            # Add analysis data if successful
            if result.success and hasattr(result, 'analysis') and result.analysis:
                analysis = result.analysis
                url_result.store_image = analysis.get('store_image', False)
                url_result.text_content = analysis.get('text_content')
                url_result.store_name = analysis.get('store_name')
                url_result.business_contact = analysis.get('business_contact')
                url_result.phone_number = analysis.get('phone_number', False)
                url_result.image_description = analysis.get(
                    'image_description')
                url_result.analysis_result = analysis

                # Compute phone matching between CSV input and AI-extracted contact
                try:
                    import re

                    def _digits_only(s: str) -> str:
                        if not s:
                            return ''
                        return re.sub(r"\D", '', str(s))

                    csv_phone_raw = listing.get('phone_number') if listing else (
                        url_result.input_phone_number or '')
                    csv_norm = _digits_only(csv_phone_raw)

                    detected_contacts = []
                    ac = analysis.get('business_contact', [])
                    if isinstance(ac, list):
                        detected_contacts = [str(x) for x in ac if x]
                    elif isinstance(ac, str) and ac.strip():
                        detected_contacts = [t.strip()
                                             for t in ac.split(',') if t.strip()]
                    elif url_result.business_contact:
                        detected_contacts = [
                            t.strip() for t in url_result.business_contact.split(',') if t.strip()]

                    best_score = 0
                    phone_match_label = 'Mismatch'

                    if csv_norm and detected_contacts:
                        for contact in detected_contacts:
                            contact_norm = _digits_only(contact)
                            if not contact_norm:
                                continue
                            try:
                                from rapidfuzz.fuzz import token_set_ratio
                                score = int(token_set_ratio(
                                    csv_norm, contact_norm))
                            except Exception:
                                import difflib
                                ratio = difflib.SequenceMatcher(
                                    None, csv_norm, contact_norm).ratio()
                                score = int(round(ratio * 100))

                            if score > best_score:
                                best_score = score

                        phone_match_label = 'Match' if any(_digits_only(
                            c) == csv_norm for c in detected_contacts) else 'Mismatch'
                    else:
                        best_score = 0
                        phone_match_label = 'Mismatch'

                    url_result.phone_match_score = int(
                        best_score) if best_score is not None else 0
                    url_result.phone_match = phone_match_label
                except Exception:
                    # Do not block storing results if phone matching fails
                    pass

            session.add(url_result)

        session.commit()


def _update_chunk_completion(chunk_id: str, results: List[Any]):
    """Update chunk as completed"""
    with db_manager.get_session() as session:
        chunk = session.query(ProcessingChunk).filter_by(
            chunk_id=chunk_id).first()
        if chunk:
            chunk.status = ChunkStatus.COMPLETED
            chunk.completed_at = datetime.now()
            chunk.processed_count = len(results)
            chunk.successful_count = sum(1 for r in results if r.success)
            chunk.failed_count = len(results) - chunk.successful_count

            if chunk.started_at:
                from datetime import timezone
                processing_time = (
                    datetime.now(timezone.utc) - chunk.started_at).total_seconds()
                chunk.processing_time_seconds = processing_time
                if len(results) > 0:
                    chunk.average_time_per_url = processing_time / len(results)

            session.commit()


def _update_chunk_failed(chunk_id: str, error_message: str):
    """Update chunk as failed"""
    with db_manager.get_session() as session:
        chunk = session.query(ProcessingChunk).filter_by(
            chunk_id=chunk_id).first()
        if chunk:
            chunk.status = ChunkStatus.FAILED
            chunk.completed_at = datetime.now()
            chunk.error_message = error_message

            if chunk.started_at:
                from datetime import timezone
                chunk.processing_time_seconds = (
                    datetime.now(timezone.utc) - chunk.started_at).total_seconds()

            session.commit()


def _update_batch_progress(batch_id: str):
    """Update batch progress based on completed chunks"""
    with db_manager.get_session() as session:
        batch = session.query(ProcessingBatch).filter_by(
            batch_id=batch_id).first()
        if not batch:
            return

        # Get chunk statistics
        chunks = session.query(ProcessingChunk).filter_by(
            batch_id=batch_id).all()

        total_processed = sum(chunk.processed_count or 0 for chunk in chunks)
        total_successful = sum(chunk.successful_count or 0 for chunk in chunks)
        total_failed = sum(chunk.failed_count or 0 for chunk in chunks)

        completed_chunks = sum(
            1 for chunk in chunks if chunk.status == ChunkStatus.COMPLETED)
        failed_chunks = sum(
            1 for chunk in chunks if chunk.status == ChunkStatus.FAILED)

        # Update batch statistics
        batch.processed_count = total_processed
        batch.successful_count = total_successful
        batch.failed_count = total_failed
        batch.current_chunk = completed_chunks

        # Calculate success rate
        if total_processed > 0:
            batch.success_rate = (total_successful / total_processed) * 100

        # Update batch status
        if completed_chunks + failed_chunks == batch.total_chunks:
            # All chunks are done
            if batch.status in [BatchStatus.QUEUED, BatchStatus.PROCESSING]:
                batch.status = BatchStatus.COMPLETED
                batch.completed_at = datetime.now()
                logger.info(
                    f"Batch {batch_id} completed: {total_successful} successful, {total_failed} failed")
        elif total_processed > 0 and batch.status == BatchStatus.QUEUED:
            # Mark as processing once we start processing URLs
            batch.status = BatchStatus.PROCESSING
            if not batch.started_at:
                batch.started_at = datetime.now()

        session.commit()

    # ==========================================
    # ADMINISTRATIVE FUNCTIONS FOR STUCK JOBS
    # ==========================================

    def get_queue_status(self) -> Dict[str, Any]:
        """Get comprehensive queue status including stuck jobs"""
        import redis
        import json

        stats = job_queue.get_queue_stats()

        # Additional analysis
        r = redis.Redis(host='localhost', port=6379, db=0)
        queue_name = job_queue.queue_name

        # Get stuck jobs details
        stuck_jobs = []
        job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))

        for job_key in job_keys:
            job_data = r.get(job_key)
            if job_data:
                try:
                    job_info = json.loads(job_data)
                    job_type = job_info.get('job_type', 'unknown')
                    status = job_info.get('status', 'unknown')

                    # Identify problematic jobs
                    if job_type == 'process_chunk' or status in ['retrying', 'processing']:
                        stuck_jobs.append({
                            'job_id': job_info.get('job_id'),
                            'job_type': job_type,
                            'status': status,
                            'retry_count': job_info.get('retry_count', 0),
                            'created_at': job_info.get('created_at'),
                            'batch_id': job_info.get('payload', {}).get('batch_id'),
                            'chunk_id': job_info.get('payload', {}).get('chunk_id')
                        })
                except Exception:
                    continue

        return {
            'queue_stats': stats,
            'stuck_jobs': stuck_jobs,
            'total_stuck': len(stuck_jobs),
            'recommendations': self._get_cleanup_recommendations(stats, stuck_jobs)
        }

    def _get_cleanup_recommendations(self, stats: Dict[str, int], stuck_jobs: List[Dict]) -> List[str]:
        """Generate recommendations for cleaning up the queue"""
        recommendations = []

        if stats.get('retrying', 0) > 0:
            recommendations.append(
                f"Clear {stats['retrying']} stuck retrying jobs")

        if stats.get('processing', 0) > 0:
            old_processing = [
                j for j in stuck_jobs if j['status'] == 'processing']
            if old_processing:
                recommendations.append(
                    f"Clear {len(old_processing)} old processing jobs with no active worker")

        old_job_types = [
            j for j in stuck_jobs if j['job_type'] == 'process_chunk']
        if old_job_types:
            recommendations.append(
                f"Remove {len(old_job_types)} jobs with obsolete job type 'process_chunk'")

        if not recommendations:
            recommendations.append("Queue is clean - no action needed")

        return recommendations

    def cleanup_stuck_jobs(self, job_types_to_remove: List[str] = None,
                           max_age_hours: int = 24) -> Dict[str, Any]:
        """Clean up stuck jobs in the queue"""
        import redis
        import json
        from datetime import datetime, timedelta

        if job_types_to_remove is None:
            # Default to removing old job type
            job_types_to_remove = ['process_chunk']

        r = redis.Redis(host='localhost', port=6379, db=0)
        queue_name = job_queue.queue_name

        # Get all job keys
        job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))

        jobs_to_remove = []
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

        for job_key in job_keys:
            job_data = r.get(job_key)
            if job_data:
                try:
                    job_info = json.loads(job_data)
                    job_type = job_info.get('job_type', 'unknown')
                    created_at_str = job_info.get('created_at', '')

                    # Check if job should be removed
                    should_remove = False

                    # Remove by job type
                    if job_type in job_types_to_remove:
                        should_remove = True

                    # Remove old stuck jobs
                    if created_at_str:
                        try:
                            created_at = datetime.fromisoformat(
                                created_at_str.replace('Z', '+00:00'))
                            if created_at < cutoff_time and job_info.get('status') in ['retrying', 'processing']:
                                should_remove = True
                        except Exception:
                            pass

                    if should_remove:
                        jobs_to_remove.append({
                            'job_id': job_info.get('job_id'),
                            'job_key': job_key.decode('utf-8') if isinstance(job_key, bytes) else str(job_key),
                            'job_type': job_type,
                            'status': job_info.get('status', 'unknown')
                        })

                except Exception:
                    continue

        # Remove the jobs
        removed_count = 0
        for job in jobs_to_remove:
            job_id = job['job_id']

            # Remove from all sets
            r.srem(f"{queue_name}:processing", job_id)
            r.srem(f"{queue_name}:retrying", job_id)
            r.zrem(f"{queue_name}:retry", job_id)

            # Delete job data
            r.delete(job['job_key'])

            removed_count += 1
            logger.info(
                f"Removed stuck job {job_id} (type: {job['job_type']}, status: {job['status']})")

        # Get final stats
        final_stats = job_queue.get_queue_stats()

        return {
            'removed_count': removed_count,
            'removed_jobs': jobs_to_remove,
            'final_stats': final_stats,
            'message': f"Successfully removed {removed_count} stuck jobs"
        }

    def get_all_batches(self, page: int = 1, per_page: int = 20, status_filter: str = None, include_soft_deleted: bool = False) -> List[Dict[str, Any]]:
        """Get all batches with pagination and filtering"""
        with db_manager.get_session() as session:
            query = session.query(ProcessingBatch)

            # Exclude soft deleted batches unless explicitly requested
            if not include_soft_deleted:
                query = query.filter(
                    ~((ProcessingBatch.status == BatchStatus.CANCELLED) &
                      (ProcessingBatch.error_message.like('%Soft deleted%')))
                )

            # Apply status filter if provided
            if status_filter:
                try:
                    status_enum = BatchStatus(status_filter.lower())
                    query = query.filter(ProcessingBatch.status == status_enum)
                except ValueError:
                    logger.warning(f"Invalid status filter: {status_filter}")

            # Apply pagination
            offset = (page - 1) * per_page
            batches = query.order_by(ProcessingBatch.created_at.desc()).offset(
                offset).limit(per_page).all()

            result = []
            for batch in batches:
                # Get batch statistics
                chunks_stats = session.query(ProcessingChunk).filter_by(
                    batch_id=batch.batch_id).all()

                # Calculate progress
                total_chunks = len(chunks_stats)
                completed_chunks = sum(
                    1 for chunk in chunks_stats if chunk.status == ChunkStatus.COMPLETED)
                progress_percentage = (
                    completed_chunks / total_chunks * 100) if total_chunks > 0 else 0

                batch_info = {
                    'batch_id': str(batch.batch_id),
                    'batch_name': batch.batch_name,
                    'status': batch.status.value.upper(),
                    'total_urls': batch.total_urls,
                    'total_chunks': total_chunks,
                    'completed_chunks': completed_chunks,
                    'processed_count': batch.processed_count,
                    'successful_count': batch.successful_count,
                    'failed_count': batch.failed_count,
                    'progress_percentage': round(progress_percentage, 1),
                    'created_at': batch.created_at.isoformat() if batch.created_at else None,
                    'started_at': batch.started_at.isoformat() if batch.started_at else None,
                    'completed_at': batch.completed_at.isoformat() if batch.completed_at else None,
                    'processing_time_seconds': batch.processing_time_seconds,
                    'error_message': batch.error_message
                }
                result.append(batch_info)

            return result


# Job handler functions for the job queue system
def process_chunk_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Job handler for processing chunks"""
    try:
        batch_id = payload.get('batch_id')
        chunk_id = payload.get('chunk_id')

        if not batch_id or not chunk_id:
            return {
                'success': False,
                'error': 'Missing batch_id or chunk_id in payload'
            }

        logger.info(f"Processing chunk {chunk_id} for batch {batch_id}")

        with db_manager.get_session() as session:
            # Get chunk details
            chunk = session.query(ProcessingChunk).filter_by(
                chunk_id=chunk_id, batch_id=batch_id).first()

            if not chunk:
                return {
                    'success': False,
                    'error': f'Chunk {chunk_id} not found'
                }

            # Get URLs from chunk.urls (JSON field)
            urls = chunk.urls or []

            if not urls:
                return {
                    'success': False,
                    'error': f'No URLs found for chunk {chunk_id}'
                }

            # Process each URL in the chunk
            successful_count = 0
            failed_count = 0

            chunk.status = ChunkStatus.PROCESSING
            chunk.started_at = BatchManager._utc_now()
            session.commit()

            for url in urls:
                try:
                    # Import processor here to avoid circular imports
                    from .processor import image_processor
                    from .cache import get_cache

                    # Get cache instance
                    cache = get_cache()

                    # Check if URL is in cache
                    cached_analysis = cache.get_analysis(url)

                    if cached_analysis:
                        # Use cached result
                        result = {
                            'success': True,
                            'analysis': cached_analysis,
                            'cache_hit': True,
                            'processing_time': 0.0
                        }
                    else:
                        # Process URL
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        processing_result = loop.run_until_complete(
                            image_processor.process_single_url(url)
                        )

                        result = {
                            'success': processing_result.success,
                            'analysis': processing_result.analysis if processing_result.success else None,
                            'error': processing_result.error if not processing_result.success else None,
                            'cache_hit': False,
                            'processing_time': processing_result.processing_time
                        }

                        # Cache successful results
                        if result['success'] and result['analysis']:
                            cache.set_analysis(url, result['analysis'])

                    # Generate URL hash for database constraint
                    url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()

                    # Store result in database
                    analysis_result = URLAnalysisResult(
                        batch_id=batch_id,
                        chunk_id=chunk_id,
                        url=url,
                        url_hash=url_hash,
                        success=result.get('success', False),
                        error_message=result.get('error'),
                        processing_time_seconds=result.get(
                            'processing_time', 0.0),
                        cache_hit=result.get('cache_hit', False)
                    )

                    # Add analysis data if successful
                    if result.get('success') and result.get('analysis'):
                        analysis = result['analysis']
                        analysis_result.store_image = analysis.get(
                            'store_image', False)
                        analysis_result.text_content = analysis.get(
                            'text_content')
                        analysis_result.store_name = analysis.get('store_name')
                        analysis_result.business_contact = analysis.get(
                            'business_contact')
                        analysis_result.phone_number = analysis.get(
                            'phone_number', False)
                        analysis_result.image_description = analysis.get(
                            'image_description')
                        analysis_result.analysis_result = analysis

                    session.add(analysis_result)

                    if result.get('success'):
                        successful_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    logger.error(f"Error analyzing URL {url}: {e}")

                    # Generate URL hash for database constraint
                    url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()

                    # Store failed result
                    analysis_result = URLAnalysisResult(
                        batch_id=batch_id,
                        chunk_id=chunk_id,
                        url=url,
                        url_hash=url_hash,
                        success=False,
                        error_message=str(e),
                        processing_time_seconds=0.0,
                        cache_hit=False
                    )
                    session.add(analysis_result)
                    failed_count += 1

            # Update chunk status
            chunk.status = ChunkStatus.COMPLETED
            chunk.completed_at = datetime.now()
            chunk.processed_count = len(urls)
            chunk.successful_count = successful_count
            chunk.failed_count = failed_count

            if chunk.started_at:
                processing_time = (chunk.completed_at -
                                   chunk.started_at).total_seconds()
                chunk.processing_time_seconds = processing_time

            session.commit()

            # Update overall batch status
            _update_batch_progress(batch_id)

            logger.info(
                f"Completed chunk {chunk_id}: {successful_count} successful, {failed_count} failed")

            return {
                'success': True,
                'chunk_id': chunk_id,
                'processed_count': len(urls),
                'successful_count': successful_count,
                'failed_count': failed_count
            }

    except Exception as e:
        logger.error(f"Error in process_chunk_handler: {e}")
        return {
            'success': False,
            'error': str(e)
        }
