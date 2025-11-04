#!/usr/bin/env python3
"""
Cloud Run HTTP server wrapper for Background Worker
Provides health check endpoint on port 8080 while running background jobs.
"""
import signal
from flask import Flask, jsonify, request
import sys
import os
import asyncio
import logging
from threading import Thread

# Add the project root to Python path for proper imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)  # Go up to project root
sys.path.insert(0, parent_dir)


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app for HTTP health checks
app = Flask(__name__)

# Global variable to track worker status
worker_thread = None
stop_event = None


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    return jsonify({
        'status': 'healthy',
        'service': 'image-analyzer-worker'
    }), 200


@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({
        'service': 'image-analyzer-worker',
        'status': 'running'
    }), 200


@app.route('/process', methods=['POST'])
def process_trigger():
    """Process trigger endpoint for Cloud Scheduler and external triggers"""
    try:
        # Get the request data
        data = request.get_json() if request.is_json else {}
        trigger_type = data.get('trigger', 'unknown')

        logger.info(f"Process endpoint triggered: {trigger_type}")

        # The background workers are already running and polling the job queue
        # This endpoint just acknowledges the trigger
        return jsonify({
            'status': 'success',
            'message': f'Worker trigger acknowledged: {trigger_type}',
            'service': 'image-analyzer-worker',
            'trigger_type': trigger_type
        }), 200

    except Exception as e:
        logger.error(f"Error in process endpoint: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'service': 'image-analyzer-worker'
        }), 500


@app.route('/status', methods=['GET'])
def status_check():
    """Status endpoint for monitoring worker state"""
    try:
        global worker_thread

        worker_status = 'running' if worker_thread and worker_thread.is_alive() else 'stopped'

        return jsonify({
            'status': 'healthy',
            'service': 'image-analyzer-worker',
            'worker_thread_status': worker_status,
            'endpoints': {
                'health': '/health',
                'status': '/status',
                'process': '/process (POST)',
                'root': '/'
            }
        }), 200

    except Exception as e:
        logger.error(f"Error in status endpoint: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'service': 'image-analyzer-worker'
        }), 500


def run_worker():
    """Run the background worker"""
    try:
        import threading
        from src.background_worker import run_worker_process, worker_manager

        logger.info("Starting Background Workers in Cloud Run...")

        # Get worker configuration from environment
        num_workers = int(os.environ.get('NUM_WORKERS', 10))
        worker_id = os.environ.get('WORKER_ID', 'cloud-run-worker')

        logger.info(f"Number of workers: {num_workers}")
        logger.info(f"Worker ID: {worker_id}")

        # Setup signal handlers only if we're in the main thread
        if threading.current_thread() is threading.main_thread():
            import signal

            def signal_handler(signum, frame):
                logger.info(f"Worker {worker_id} received signal {signum}")
                # Set the stop flag if worker_manager exists
                if 'worker_manager' in globals() and worker_manager:
                    worker_manager.should_stop = True

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            logger.info("Signal handlers set up in main thread")
        else:
            logger.info(
                "Running in worker thread - signal handlers not available")

        # Run the worker process
        asyncio.run(run_worker_process(worker_id, num_workers))

    except KeyboardInterrupt:
        logger.info("Background workers stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start workers: {e}", exc_info=True)
        sys.exit(1)


def run_http_server():
    """Run HTTP server - Gunicorn in production, Flask dev server locally"""
    port = int(os.environ.get('PORT', 8080))

    # Check if we're running in Cloud Run (production)
    is_production = os.environ.get(
        'K_SERVICE') is not None  # Cloud Run sets this

    if is_production:
        logger.info(f"Starting Gunicorn WSGI server on port {port}")

        # Import Gunicorn programmatically
        try:
            from gunicorn.app.base import BaseApplication

            class StandaloneApplication(BaseApplication):
                def __init__(self, app, options=None):
                    self.options = options or {}
                    self.application = app
                    super().__init__()

                def load_config(self):
                    config = {key: value for key, value in self.options.items()
                              if key in self.cfg.settings and value is not None}
                    for key, value in config.items():
                        self.cfg.set(key.lower(), value)

                def load(self):
                    return self.application

            # Gunicorn configuration for production
            options = {
                'bind': f'0.0.0.0:{port}',
                'workers': 1,  # Single worker for simplicity in Cloud Run
                'worker_class': 'sync',
                'timeout': 300,  # 5 minutes timeout for long-running requests
                'keepalive': 30,
                'max_requests': 1000,
                'max_requests_jitter': 100,
                'preload_app': True,
                'capture_output': True,
                'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s',
            }

            StandaloneApplication(app, options).run()

        except ImportError:
            logger.warning(
                "Gunicorn not available, falling back to Flask dev server")
            logger.warning("This is not recommended for production!")
            app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

    else:
        logger.info(f"Starting Flask development server on port {port}")
        logger.info("For production, set K_SERVICE environment variable")
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)


if __name__ == '__main__':
    try:
        logger.info("Starting Cloud Run worker with HTTP health check...")

        # Start worker in background thread
        worker_thread = Thread(target=run_worker, daemon=False)
        worker_thread.start()
        logger.info("Background worker thread started")

        # Start HTTP server in main thread (blocking)
        # This allows Cloud Run to connect to the health check endpoint
        run_http_server()

    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
