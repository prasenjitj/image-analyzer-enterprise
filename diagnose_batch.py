#!/usr/bin/env python3
"""
Diagnostic script to check why a batch hasn't been picked
"""
import sys
import json
from datetime import datetime
from src.database_models import (
    ProcessingBatch, ProcessingChunk, db_manager,
    BatchStatus, ChunkStatus
)
from src.job_queue import job_queue


def diagnose_batch(batch_id: str):
    """Comprehensive diagnosis of a batch"""

    print(f"\n{'='*80}")
    print(f"BATCH DIAGNOSTIC REPORT: {batch_id}")
    print(f"{'='*80}\n")

    try:
        with db_manager.get_session() as session:
            # 1. Get batch details
            print("1. BATCH INFORMATION")
            print("-" * 80)
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                print(f"❌ BATCH NOT FOUND: {batch_id}")
                return

            print(f"✓ Batch ID: {batch.batch_id}")
            print(f"✓ Batch Name: {batch.batch_name}")
            print(f"✓ Status: {batch.status.value.upper()}")
            print(f"✓ Created At: {batch.created_at}")
            print(f"✓ Started At: {batch.started_at}")
            print(f"✓ Completed At: {batch.completed_at}")
            print(f"✓ Total URLs: {batch.total_urls}")
            print(f"✓ Processed: {batch.processed_count}")
            print(f"✓ Successful: {batch.successful_count}")
            print(f"✓ Failed: {batch.failed_count}")
            print(f"✓ Total Chunks: {batch.total_chunks}")
            print(f"✓ Current Chunk: {batch.current_chunk}")

            if batch.error_message:
                print(f"⚠ Error: {batch.error_message}")

            # 2. Analyze batch status
            print("\n2. STATUS ANALYSIS")
            print("-" * 80)

            if batch.status == BatchStatus.PENDING:
                print("⚠ STATUS IS PENDING - Batch has not been started")
                print("   ACTION REQUIRED: Call start_batch_processing(batch_id)")
                print("   OR: Click the 'Start Processing' button on the web interface")
            elif batch.status == BatchStatus.QUEUED:
                print("✓ STATUS IS QUEUED - Batch is waiting for processing")
                print("   This is normal if jobs are being picked by workers")
            elif batch.status == BatchStatus.PROCESSING:
                print("✓ STATUS IS PROCESSING - Batch is currently being processed")
            elif batch.status == BatchStatus.COMPLETED:
                print("✓ STATUS IS COMPLETED - Batch has finished processing")
            elif batch.status == BatchStatus.PAUSED:
                print("⚠ STATUS IS PAUSED - Batch has been paused")
                print("   ACTION REQUIRED: Call resume_batch(batch_id)")
            elif batch.status == BatchStatus.FAILED:
                print("❌ STATUS IS FAILED - Batch processing failed")
                print(f"   Reason: {batch.error_message}")

            # 3. Chunk analysis
            print("\n3. CHUNK ANALYSIS")
            print("-" * 80)

            chunks = session.query(ProcessingChunk).filter_by(
                batch_id=batch_id).all()
            print(f"Total Chunks: {len(chunks)}")

            chunk_status_counts = {}
            for chunk in chunks:
                status = chunk.status.value
                chunk_status_counts[status] = chunk_status_counts.get(
                    status, 0) + 1

            print(f"Chunk Status Breakdown:")
            for status, count in sorted(chunk_status_counts.items()):
                print(f"  - {status.upper()}: {count}")

            # List first few chunks
            print(f"\nFirst 5 chunks:")
            for i, chunk in enumerate(chunks[:5], 1):
                print(f"  Chunk {i}: ID={chunk.chunk_id}")
                print(f"    Status: {chunk.status.value}")
                print(f"    URL Count: {chunk.url_count}")
                print(f"    Processed: {chunk.processed_count}")
                print(f"    Successful: {chunk.successful_count}")
                print(f"    Failed: {chunk.failed_count}")
                print(f"    Worker ID: {chunk.worker_id}")
                print(f"    Started At: {chunk.started_at}")
                print(f"    Completed At: {chunk.completed_at}")
                if chunk.error_message:
                    print(f"    Error: {chunk.error_message}")
                print()

            # 4. Job queue analysis
            print("\n4. JOB QUEUE ANALYSIS")
            print("-" * 80)

            stats = job_queue.get_queue_stats()
            print(f"Job Queue Stats:")
            print(f"  Pending: {stats.get('pending', 0)}")
            print(f"  Processing: {stats.get('processing', 0)}")
            print(f"  Completed: {stats.get('completed', 0)}")
            print(f"  Failed: {stats.get('failed', 0)}")
            print(f"  Retrying: {stats.get('retrying', 0)}")

            # Try to find jobs related to this batch (if Redis available)
            if job_queue.redis_client:
                print("\n  Searching for batch-related jobs in Redis...")
                try:
                    # Get all job keys
                    all_job_keys = list(job_queue.redis_client.scan_iter(
                        match=f"{job_queue.queue_name}:job:*"
                    ))

                    batch_jobs = []
                    for job_key in all_job_keys:
                        job_data_str = job_queue.redis_client.get(job_key)
                        if job_data_str:
                            job_data = json.loads(job_data_str)
                            if job_data.get('payload', {}).get('batch_id') == str(batch_id):
                                batch_jobs.append(job_data)

                    print(
                        f"  Found {len(batch_jobs)} jobs for this batch in Redis:")
                    for j, job in enumerate(batch_jobs[:5], 1):
                        print(f"    Job {j}:")
                        print(f"      Job ID: {job.get('job_id')}")
                        print(f"      Status: {job.get('status')}")
                        print(f"      Job Type: {job.get('job_type')}")
                        print(
                            f"      Chunk ID: {job.get('payload', {}).get('chunk_id')}")
                        print(
                            f"      Retry Count: {job.get('retry_count', 0)}")
                        print(f"      Worker ID: {job.get('worker_id')}")
                except Exception as e:
                    print(f"  Could not search Redis: {e}")

            # 5. Diagnosis and recommendations
            print("\n5. DIAGNOSIS & RECOMMENDATIONS")
            print("-" * 80)

            issues = []
            recommendations = []

            # Check batch status
            if batch.status == BatchStatus.PENDING:
                issues.append("Batch has not been started")
                recommendations.append(
                    "Start the batch using start_batch_processing() or web UI")

            # Check if chunks were created
            if len(chunks) == 0:
                issues.append("No chunks were created for this batch")
                recommendations.append("Check if batch creation succeeded")

            # Check chunk statuses
            pending_chunks = sum(
                1 for c in chunks if c.status == ChunkStatus.PENDING)
            processing_chunks = sum(
                1 for c in chunks if c.status == ChunkStatus.PROCESSING)
            completed_chunks = sum(
                1 for c in chunks if c.status == ChunkStatus.COMPLETED)
            failed_chunks = sum(
                1 for c in chunks if c.status == ChunkStatus.FAILED)

            if pending_chunks > 0 and processing_chunks == 0:
                issues.append(
                    f"{pending_chunks} chunks still pending, none processing")
                recommendations.append(
                    "Check if jobs are being dequeued by workers")
                recommendations.append("Verify background workers are running")

            if processing_chunks > 0:
                # Check for stalled chunks
                now = datetime.now(
                    batch.created_at.tzinfo) if batch.created_at.tzinfo else datetime.now()
                stalled_chunks = 0
                for chunk in chunks:
                    if chunk.status == ChunkStatus.PROCESSING and chunk.started_at:
                        age_seconds = (now - chunk.started_at).total_seconds()
                        if age_seconds > 3600:  # Older than 1 hour
                            stalled_chunks += 1

                if stalled_chunks > 0:
                    issues.append(
                        f"{stalled_chunks} chunks stuck in PROCESSING for >1 hour")
                    recommendations.append(
                        "These chunks may be stalled - consider resetting them")
                    recommendations.append(
                        "Use reset_stuck_batch() to recover")

            if failed_chunks > 0:
                issues.append(f"{failed_chunks} chunks have failed")
                recommendations.append(
                    "Check chunk error messages for failure reasons")
                recommendations.append(
                    "Fix underlying issue and retry the batch")

            # Check for workers
            from src.background_worker import worker_manager
            worker_status = worker_manager.get_worker_status()
            if worker_status['active_workers'] == 0:
                issues.append("No active background workers")
                recommendations.append("Start background workers:")
                recommendations.append("  python -m src.run_worker_http")

            if not issues:
                print("✓ NO ISSUES DETECTED")
                print("  Batch appears to be processing normally")
            else:
                print("⚠ ISSUES FOUND:")
                for i, issue in enumerate(issues, 1):
                    print(f"  {i}. {issue}")

                print("\n📋 RECOMMENDATIONS:")
                for i, rec in enumerate(recommendations, 1):
                    print(f"  {i}. {rec}")

    except Exception as e:
        print(f"❌ ERROR during diagnosis: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python diagnose_batch.py <batch_id>")
        print("\nExample:")
        print("  python diagnose_batch.py 1eb945ab-5408-470e-8d32-b933c04ceb44")
        sys.exit(1)

    batch_id = sys.argv[1]
    diagnose_batch(batch_id)
