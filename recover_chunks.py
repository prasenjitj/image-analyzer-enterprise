#!/usr/bin/env python3
"""
Manual recovery script to re-queue orphaned chunks
"""
import logging
from src.job_queue import enqueue_chunk_processing
from src.database_models import ProcessingBatch, ProcessingChunk, BatchStatus, ChunkStatus, db_manager
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def recover_orphaned_chunks():
    """Re-queue chunks that are PENDING or stuck in PROCESSING"""
    recovered_count = 0

    with db_manager.get_session() as session:
        # Find all active batches (QUEUED or PROCESSING)
        active_batches = session.query(ProcessingBatch).filter(
            ProcessingBatch.status.in_(
                [BatchStatus.QUEUED, BatchStatus.PROCESSING])
        ).all()

        logger.info(f"Found {len(active_batches)} active batches")

        for batch in active_batches:
            # Find chunks that need processing
            orphaned_chunks = session.query(ProcessingChunk).filter(
                ProcessingChunk.batch_id == batch.batch_id,
                ProcessingChunk.status.in_(
                    [ChunkStatus.PENDING, ChunkStatus.PROCESSING])
            ).all()

            logger.info(
                f"Batch {batch.batch_id}: {len(orphaned_chunks)} orphaned chunks")

            for chunk in orphaned_chunks:
                # Reset PROCESSING chunks back to PENDING
                if chunk.status == ChunkStatus.PROCESSING:
                    chunk.status = ChunkStatus.PENDING
                    chunk.started_at = None
                    chunk.worker_id = None
                    session.commit()
                    logger.info(
                        f"Reset PROCESSING chunk {chunk.chunk_id} to PENDING")

                # Re-queue the chunk
                try:
                    enqueue_chunk_processing(
                        str(batch.batch_id),
                        str(chunk.chunk_id),
                        chunk.urls  # This contains listing data
                    )
                    recovered_count += 1
                    logger.info(f"Re-queued chunk {chunk.chunk_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to re-queue chunk {chunk.chunk_id}: {e}")

    logger.info(f"Recovery complete: {recovered_count} chunks re-queued")
    return recovered_count


if __name__ == "__main__":
    recovered = recover_orphaned_chunks()
    print(f"\n✅ Recovered {recovered} chunks")
