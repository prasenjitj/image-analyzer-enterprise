#!/usr/bin/env python3
"""
Cloud Run entry point for Background Worker
Properly handles imports and starts background workers as a service.
"""
import logging
import asyncio
import sys
import os

# Add the project root to Python path for proper imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)  # Go up to project root
sys.path.insert(0, parent_dir)


# Setup logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

if __name__ == '__main__':
    try:
        # Import after sys.path is configured
        from src.background_worker import run_worker_process

        logger.info("Starting Background Workers in Cloud Run...")

        # Get worker configuration from environment
        num_workers = int(os.environ.get('NUM_WORKERS', 10))
        worker_id = os.environ.get('WORKER_ID', 'cloud-run-worker')

        logger.info(f"Number of workers: {num_workers}")
        logger.info(f"Worker ID: {worker_id}")

        # Run the worker process
        asyncio.run(run_worker_process(worker_id, num_workers))

    except KeyboardInterrupt:
        logger.info("Background workers stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start workers: {e}", exc_info=True)
        sys.exit(1)
