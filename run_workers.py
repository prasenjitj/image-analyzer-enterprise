#!/usr/bin/env python3
"""
Background Worker launcher script for the enterprise system.
This script handles the imports properly and starts background workers.
"""
import sys
import os
import argparse

# Add the src directory to Python path
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
sys.path.insert(0, src_dir)

if __name__ == '__main__':
    # Change to src directory
    os.chdir(src_dir)

    # Parse arguments
    parser = argparse.ArgumentParser(description="Background Worker Process")
    parser.add_argument("--workers", type=int, default=10,
                        help="Number of workers (default: 10)")
    parser.add_argument(
        "--worker-id", help="Worker ID (auto-generated if not provided)")

    args = parser.parse_args()

    # Import and run the background worker
    from background_worker import run_worker_process
    import asyncio
    import logging

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print(f"Starting Background Workers...")
    print(f"Number of workers: {args.workers}")
    print(f"Worker ID: {args.worker_id or 'auto-generated'}")
    print("Press Ctrl+C to stop the workers")

    try:
        asyncio.run(run_worker_process(args.worker_id, args.workers))
    except KeyboardInterrupt:
        print("\nBackground workers stopped by user")
    except Exception as e:
        print(f"Background workers failed: {e}")
        sys.exit(1)
