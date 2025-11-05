"""
Enterprise Flask application for scalable batch image processing

Integrates PostgreSQL, Redis, batch management, and polling APIs for 15M URL processing
"""
from typing import Tuple
import os
import logging
import signal
import sys
import time
import json
import redis
from datetime import datetime
from sqlalchemy import text  # Add SQLAlchemy text for database queries
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, make_response
from werkzeug.utils import secure_filename

# Import enterprise components
from .enterprise_config import config
from .database_models import db_manager, ProcessingBatch
from .job_queue import job_queue, start_background_workers
from .batch_manager import batch_manager
from .polling_api import polling_api
from .export_manager import export_manager
from .export_api import export_api

# Connection retry utilities
from sqlalchemy.exc import OperationalError, ArgumentError
import socket

# Original components (for fallback functionality) - commented out missing modules
# from .main import ScalableImageAnalyzer
# from .monitoring import MonitoringDashboard
# from .cache import get_cache

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(
            config.log_dir, 'enterprise_app.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# Database Connection Diagnostics and Recovery
# ============================================================================

def diagnose_connection_issue(db_url: str, error: Exception) -> str:
    """
    Diagnose the root cause of database connection failure

    Args:
        db_url: PostgreSQL connection URL
        error: The exception that was raised

    Returns:
        Diagnostic message with suggestions
    """
    error_str = str(error).lower()

    # Parse connection URL for diagnostics
    from urllib.parse import urlparse
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432

        # Check if using private IP
        is_private = host.startswith(('10.', '172.', '192.168'))

    except Exception:
        host = "unknown"
        port = "unknown"
        is_private = False

    diagnostics = []

    # Classify error and provide guidance
    if "connection timed out" in error_str or "timeout" in error_str:
        diagnostics.extend([
            f"Connection Timeout to {host}:{port}",
            "Possible causes:",
            "1. VPC Connector not configured (for private IPs)",
            "2. VPC Connector not yet READY (still creating)",
            "3. Firewall rules blocking traffic",
            "4. Database server not listening on expected port",
            "5. Network routing issue between Cloud Run and database",
            "",
            "Immediate actions:",
            "- Run: python diagnostic_db_connection.py",
            "- Run: bash validate_vpc_connector.sh PROJECT_ID REGION",
            f"- Check database is listening: ssh DB_HOST 'netstat -tlnp | grep {port}'",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md for detailed guide"
        ])

    elif "connection refused" in error_str:
        diagnostics.extend([
            f"Connection Refused to {host}:{port}",
            "Possible causes:",
            "1. PostgreSQL server not running",
            "2. PostgreSQL not listening on port or IP",
            "3. Firewall blocking connections",
            "",
            "Immediate actions:",
            f"- Check PostgreSQL is running: ssh DB_HOST 'systemctl status postgresql'",
            f"- Check if listening: ssh DB_HOST 'netstat -tlnp | grep 5432'",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md Step 6"
        ])

    elif "password authentication failed" in error_str or "authentication failed" in error_str:
        diagnostics.extend([
            "Authentication Failed",
            "Possible causes:",
            "1. Incorrect password in DATABASE_URL",
            "2. User doesn't exist in PostgreSQL",
            "",
            "Immediate actions:",
            "- Verify DATABASE_URL credentials",
            "- Check user exists: ssh DB_HOST 'sudo -u postgres psql -l'",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md Step 2"
        ])

    elif "does not exist" in error_str:
        diagnostics.extend([
            "Database or User Does Not Exist",
            "Possible causes:",
            "1. Database name wrong in DATABASE_URL",
            "2. User doesn't exist",
            "",
            "Immediate actions:",
            "- Verify database and user in DATABASE_URL",
            "- Check: ssh DB_HOST 'sudo -u postgres psql -l'",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md Step 2"
        ])

    else:
        diagnostics.extend([
            f"Database Connection Error: {type(error).__name__}",
            f"Error details: {error_str}",
            "",
            "Immediate actions:",
            "- Run diagnostics: python diagnostic_db_connection.py",
            "- Check DATABASE_URL is set correctly",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md"
        ])

    if is_private:
        diagnostics.extend([
            "",
            "NOTE: Private IP detected ({host})",
            "- This requires Serverless VPC Connector",
            "- See: POSTGRESQL_TIMEOUT_TROUBLESHOOTING.md Step 3-5"
        ])

    return "\n".join(diagnostics)


def test_database_connectivity(db_url: str, timeout: int = 5) -> Tuple[bool, str]:
    """
    Test database connectivity and return status

    Args:
        db_url: PostgreSQL connection URL
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(db_url)
        host = parsed.hostname
        port = parsed.port or 5432

        # Test network connectivity first
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return True, f"Network connectivity OK to {host}:{port}"
            elif result == 110:
                return False, f"Connection timeout to {host}:{port} - timeout"
            elif result == 111:
                return False, f"Connection refused by {host}:{port} - server not listening"
            else:
                return False, f"Connection error {result} to {host}:{port}"

        except socket.timeout:
            return False, f"Socket timeout connecting to {host}:{port}"
        except Exception as e:
            return False, f"Socket error: {e}"

    except Exception as e:
        return False, f"Error parsing connection string: {e}"


def initialize_database_with_retries(max_attempts: int = 5,
                                     initial_delay: float = 1.0) -> bool:
    """
    Initialize database with exponential backoff retry logic

    Args:
        max_attempts: Maximum number of connection attempts
        initial_delay: Initial delay in seconds

    Returns:
        True if successful, False if all attempts failed
    """
    attempt = 1
    delay = initial_delay

    while attempt <= max_attempts:
        try:
            logger.info(
                f"Database initialization attempt {attempt}/{max_attempts}...")

            # Test network connectivity first
            net_ok, net_msg = test_database_connectivity(config.database_url)
            if not net_ok:
                logger.warning(f"Network test failed: {net_msg}")
                # Network issue - worth retrying after delay
            else:
                logger.info(f"Network test passed: {net_msg}")

            # Try to create tables
            logger.info("Creating database tables...")
            db_manager.create_tables()

            # Verify connection by running a simple query
            logger.info("Verifying database connection with test query...")
            session = db_manager.get_session()
            try:
                session.execute(text("SELECT 1"))
                session.close()
            except Exception as e:
                session.close()
                raise e

            logger.info("✅ Database initialized successfully!")
            return True

        except OperationalError as e:
            logger.error(
                f"Database operational error (attempt {attempt}/{max_attempts}): {e}")
            logger.error(diagnose_connection_issue(config.database_url, e))

            if attempt < max_attempts:
                logger.info(f"Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                delay = min(delay * 2, 30)  # Cap at 30 seconds

            attempt += 1

        except ArgumentError as e:
            # Connection string format error - don't retry
            logger.error(f"Invalid database URL format: {e}")
            logger.error("Check DATABASE_URL environment variable")
            return False

        except Exception as e:
            logger.error(
                f"Unexpected error during database initialization: {e}")
            logger.error(diagnose_connection_issue(config.database_url, e))

            if attempt < max_attempts:
                logger.info(f"Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
                delay = min(delay * 2, 30)

            attempt += 1

    logger.error(
        f"❌ Failed to initialize database after {max_attempts} attempts")
    return False


# ============================================================================
# Application Factory
# ============================================================================


def create_enterprise_app():
    """Create and configure the enterprise Flask application"""

    # Create Flask app
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    # Configure Flask app
    app.config.update({
        'SECRET_KEY': config.secret_key,
        'MAX_CONTENT_LENGTH': config.max_upload_size,
        'UPLOAD_FOLDER': config.upload_dir,
        'JSON_SORT_KEYS': False,
        'JSONIFY_PRETTYPRINT_REGULAR': True
    })

    # Initialize enterprise components with retry logic
    db_initialized = False
    workers_started = False

    try:
        # Optionally skip DB initialization during cold start for serverless
        skip_db_init = os.environ.get(
            'SKIP_DB_INIT_ON_STARTUP', 'false').lower() == 'true'
        if skip_db_init:
            logger.info(
                "Skipping database initialization on startup (SKIP_DB_INIT_ON_STARTUP=true)")
            db_initialized = False
        else:
            # Initialize database with exponential backoff
            logger.info(
                "Initializing database connection (with retry logic)...")
            db_initialized = initialize_database_with_retries(
                max_attempts=5, initial_delay=1.0)

        if not db_initialized:
            logger.warning(
                "Database initialization failed - some features may not work")

        # Job queue is initialized automatically
        logger.info("Job queue ready...")

        # Start background workers (only if database is ready)
        if db_initialized:
            try:
                logger.info("Starting background workers...")
                start_background_workers(num_workers=config.max_workers)
                workers_started = True
                logger.info("Enterprise components initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to start background workers: {e}")
                logger.info(
                    "Application will continue with limited functionality")
        else:
            logger.warning(
                "Skipping background worker startup due to database initialization failure")

    except Exception as e:
        logger.error(f"Failed to initialize enterprise components: {e}")
        # Fallback to original system
        logger.info("Falling back to original processing system")

        # Initialize original components - commented out missing modules
        # app.analyzer = ScalableImageAnalyzer(enable_signal_handlers=False)
        # app.monitor = MonitoringDashboard()
        # app.cache = get_cache(config.cache_db_path)

    # Register API blueprints
    app.register_blueprint(polling_api)
    app.register_blueprint(export_api)

    # Store initialization status in app context
    app.db_initialized = db_initialized
    app.workers_started = workers_started

    # Main dashboard route
    @app.route('/')
    def dashboard():
        """Main dashboard with enterprise batch processing interface"""
        try:
            # Get system statistics
            system_stats = batch_manager.get_batch_summary_stats()

            # Get recent batches (excluding soft deleted ones)
            recent_batches = batch_manager.list_batches(
                limit=10, include_soft_deleted=False)

            return render_template('modern_enterprise_dashboard.html',
                                   system_stats=system_stats,
                                   recent_batches=recent_batches,
                                   config=config)

        except Exception as e:
            logger.error(f"Error loading dashboard: {e}")
            # Fallback to basic dashboard with minimal data
            return render_template('modern_enterprise_dashboard.html',
                                   system_stats={
                                       'total_batches': 0,
                                       'active_batches': 0,
                                       'completed_batches': 0,
                                       'total_urls_processed': 0,
                                       'successful_urls': 0,
                                       'overall_success_rate': 0.0,
                                       'queue_stats': {
                                           'pending': 0,
                                           'processing': 0,
                                           'completed': 0,
                                           'failed': 0,
                                           'retrying': 0
                                       }
                                   },
                                   recent_batches=[],
                                   config=config)

    # Batch management endpoints
    @app.route('/batch/pause/<batch_id>', methods=['POST'])
    def pause_batch(batch_id: str):
        """Pause a specific batch"""
        try:
            success = batch_manager.pause_batch(batch_id)
            return jsonify({'success': success})
        except Exception as e:
            logger.error(f"Error pausing batch {batch_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/batch/resume/<batch_id>', methods=['POST'])
    def resume_batch(batch_id: str):
        """Resume a specific batch"""
        try:
            success = batch_manager.resume_batch(batch_id)
            return jsonify({'success': success})
        except Exception as e:
            logger.error(f"Error resuming batch {batch_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/batch/cancel/<batch_id>', methods=['POST'])
    def cancel_batch(batch_id: str):
        """Cancel a specific batch"""
        try:
            success = batch_manager.cancel_batch(batch_id)
            return jsonify({'success': success})
        except Exception as e:
            logger.error(f"Error canceling batch {batch_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/batch/retry/<batch_id>', methods=['POST'])
    def retry_batch(batch_id: str):
        """Retry a specific batch"""
        try:
            result = batch_manager.retry_batch(batch_id)

            if not result.get('success', False):
                # Batch not found or cannot be retried
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Failed to retry batch'),
                    'id': batch_id
                }), 404

            # Return 202 Accepted to indicate retry has been enqueued
            return jsonify({
                'success': True,
                'data': result
            }), 202
        except ValueError as e:
            # Batch not found
            logger.warning(f"Batch not found for retry: {batch_id} - {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'id': batch_id
            }), 404
        except Exception as e:
            logger.error(f"Error retrying batch {batch_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # Bulk batch actions
    @app.route('/batch/bulk/<action>', methods=['POST'])
    def bulk_batch_action(action: str):
        """Perform bulk actions on multiple batches"""
        try:
            data = request.get_json()
            batch_ids = data.get('batch_ids', [])

            if not batch_ids:
                return jsonify({'success': False, 'error': 'No batch IDs provided'}), 400

            results = []
            for batch_id in batch_ids:
                try:
                    if action == 'pause':
                        success = batch_manager.pause_batch(batch_id)
                    elif action == 'resume':
                        success = batch_manager.resume_batch(batch_id)
                    elif action == 'cancel':
                        success = batch_manager.cancel_batch(batch_id)
                    elif action == 'retry':
                        success = batch_manager.retry_batch(batch_id)
                    else:
                        return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400

                    results.append({'batch_id': batch_id, 'success': success})
                except Exception as e:
                    results.append(
                        {'batch_id': batch_id, 'success': False, 'error': str(e)})

            successful = sum(1 for r in results if r['success'])
            return jsonify({
                'success': True,
                'results': results,
                'summary': f'{successful}/{len(batch_ids)} batches {action}ed successfully'
            })

        except Exception as e:
            logger.error(f"Error performing bulk {action}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/export/bulk', methods=['GET'])
    def bulk_export():
        """Export multiple batches in bulk"""
        try:
            batch_ids = request.args.get('batch_ids', '').split(',')
            format_type = request.args.get('format', 'csv')

            if not batch_ids or batch_ids == ['']:
                return jsonify({'error': 'No batch IDs provided'}), 400

            # Use the existing export manager for bulk export
            # Only CSV supported for this bulk endpoint
            if format_type != 'csv':
                return jsonify({'error': 'Only CSV format supported for bulk export'}), 400

            export_data_parts = []
            header_used = False
            # Known CSV headers (keep in sync with ExportManager._generate_csv_data)
            csv_headers = [
                'url', 'success', 'store_front', 'text_content', 'store_name',
                'business_contact', 'image_description', 'error_message',
                'processing_time_seconds', 'created_at', 'batch_id'
            ]

            for batch_id in batch_ids:
                batch_id = batch_id.strip()
                if not batch_id:
                    continue
                try:
                    # Use the public export method which returns CSV text
                    export_result = export_manager.export_batch_results(
                        batch_id=batch_id,
                        format_type='csv',
                        filters=None,
                        include_metadata=False
                    )

                    data = export_result.get('data', '')
                    if not data:
                        # No rows for this batch — skip but continue to ensure header later
                        continue

                    # Each export_result['data'] includes a header line as first CSV row.
                    # We want a single header in the combined CSV. Strip header from
                    # subsequent parts.
                    lines = data.splitlines()
                    if not lines:
                        continue

                    # Find first non-empty line (guard against stray newlines)
                    # and treat it as the header if it matches expected headers
                    first_line = lines[0].strip()
                    # If header not yet used, include it. Otherwise drop first line.
                    if not header_used:
                        export_data_parts.append('\n'.join(lines))
                        header_used = True
                    else:
                        # append without first line
                        if len(lines) > 1:
                            export_data_parts.append('\n'.join(lines[1:]))

                except Exception as e:
                    logger.warning(f"Failed to export batch {batch_id}: {e}")

            # If nothing produced any rows, produce a header-only CSV
            if not export_data_parts:
                header_row = ','.join(csv_headers) + '\n'
                response = make_response(header_row)
                response.headers['Content-Type'] = 'text/csv'
                response.headers[
                    'Content-Disposition'] = f'attachment; filename=bulk_export_{int(time.time())}.csv'
                return response

            # Combine parts with blank line between batches for readability
            combined_data = '\n\n'.join(export_data_parts)
            response = make_response(combined_data)
            response.headers['Content-Type'] = 'text/csv'
            response.headers[
                'Content-Disposition'] = f'attachment; filename=bulk_export_{int(time.time())}.csv'
            return response

        except Exception as e:
            logger.error(f"Error in bulk export: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/upload', methods=['POST'])
    def upload_csv():
        """Handle CSV file upload and batch creation"""
        try:
            if 'file' not in request.files:
                return jsonify({'success': False, 'error': 'No file provided'}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'error': 'No file selected'}), 400

            if not file.filename.lower().endswith('.csv'):
                return jsonify({'success': False, 'error': 'Only CSV files are supported'}), 400

            # Get optional parameters
            batch_name = request.form.get('batch_name', '').strip()
            # Auto-start if requested (default to True for better UX)
            auto_start = request.form.get(
                'auto_start', 'true').lower() == 'true'

            # Read CSV content
            csv_content = file.read().decode('utf-8')

            # Create batch
            batch_id, batch_info = batch_manager.create_batch_from_csv(
                csv_content=csv_content,
                batch_name=batch_name,
                filename=secure_filename(file.filename)
            )

            # Auto-start if requested
            if auto_start:
                try:
                    batch_manager.start_batch_processing(batch_id)
                    batch_info['auto_started'] = True
                except Exception as e:
                    logger.warning(
                        f"Could not auto-start batch {batch_id}: {e}")
                    batch_info['auto_start_error'] = str(e)

            return jsonify({
                'success': True,
                'batch_id': batch_id,
                'batch_info': batch_info,
                'redirect_url': url_for('batch_detail', batch_id=batch_id)
            })

        except Exception as e:
            logger.error(f"Error uploading CSV: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # Batch detail page
    @app.route('/batch/<batch_id>')
    def batch_detail(batch_id: str):
        """Detailed view of a specific batch"""
        try:
            from datetime import datetime
            logger.info(f"Attempting to get batch status for: {batch_id}")
            status_data = batch_manager.get_batch_status(batch_id)
            logger.info(f"Successfully retrieved batch status for: {batch_id}")

            if not status_data:
                return render_template('error.html', error="Batch not found"), 404

            # Helper function to parse ISO dates
            def parse_iso_date(iso_string):
                if iso_string:
                    try:
                        return datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
                    except:
                        return None
                return None

            # Extract timing data
            timing_data = status_data.get('timing', {})

            # Create a flattened batch object for template compatibility
            batch_data = {
                'batch_id': status_data.get('batch_id'),
                'batch_name': status_data.get('batch_info', {}).get('batch_name'),
                'description': None,  # Add missing description field
                'status': status_data.get('status'),
                'created_at': parse_iso_date(status_data.get('batch_info', {}).get('created_at')),
                'started_at': parse_iso_date(timing_data.get('started_at')),
                'completed_at': parse_iso_date(timing_data.get('completed_at')),
                'total_urls': status_data.get('batch_info', {}).get('total_urls'),
                'processed_count': status_data.get('batch_info', {}).get('processed_count'),
                'progress_percentage': status_data.get('progress', {}).get('progress_percentage', 0),
                'success_rate': status_data.get('performance', {}).get('success_rate_percentage', 0),
                'processing_time_display': f"{status_data.get('timing', {}).get('elapsed_time_minutes', 0):.1f} minutes"
            }

            return render_template('modern_batch_detail.html',
                                   batch=batch_data,
                                   status_data=status_data)

        except ValueError as e:
            logger.warning(f"Batch not found: {e}")
            return render_template('error.html',
                                   error=f"Batch {batch_id} not found"), 404
        except Exception as e:
            logger.error(f"Error loading batch detail for {batch_id}: {e}")
            logger.exception("Full exception details:")
            return render_template('error.html',
                                   error=f"Internal server error: {str(e)}"), 500

    # Export endpoints
    @app.route('/export/batch/<batch_id>')
    def export_batch(batch_id: str):
        """Export batch results"""
        try:
            format_type = request.args.get('format', 'csv')
            include_metadata = request.args.get(
                'metadata', 'true').lower() == 'true'

            # Parse filters
            filters = {}
            if request.args.get('success_only') == 'true':
                filters['success_only'] = True
            if request.args.get('failed_only') == 'true':
                filters['failed_only'] = True

            # Generate export
            export_result = export_manager.export_batch_results(
                batch_id=batch_id,
                format_type=format_type,
                filters=filters,
                include_metadata=include_metadata
            )

            # Create response
            if format_type == 'xlsx':
                # Binary data for Excel
                response = app.response_class(
                    export_result['data'],
                    mimetype=export_result['content_type'],
                    headers={
                        'Content-Disposition': f'attachment; filename="{export_result["filename"]}"'
                    }
                )
            else:
                # Text data for CSV/JSON
                response = app.response_class(
                    export_result['data'],
                    mimetype=export_result['content_type'],
                    headers={
                        'Content-Disposition': f'attachment; filename="{export_result["filename"]}"'
                    }
                )

            return response

        except Exception as e:
            logger.error(f"Error exporting batch {batch_id}: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/export/template')
    def export_template():
        """Download CSV import template"""
        try:
            template = export_manager.get_export_template()

            response = app.response_class(
                template['data'],
                mimetype=template['content_type'],
                headers={
                    'Content-Disposition': f'attachment; filename="{template["filename"]}"'
                }
            )

            return response

        except Exception as e:
            logger.error(f"Error generating template: {e}")
            return jsonify({'error': str(e)}), 500

    # System monitoring
    @app.route('/system/status')
    def system_status():
        """System status page"""
        try:
            # Get comprehensive system status
            system_stats = batch_manager.get_batch_summary_stats()

            # Database status check with comprehensive error handling
            database_status = "error"  # Default to error state
            error_details = None
            try:
                session = db_manager.get_session()
                try:
                    # Test basic connection with quick query
                    # session.execute("SELECT 1").fetchone()
                    session.execute(text("SELECT 1")).fetchone()

                    # Verify specific table access
                    try:
                        # session.execute(
                        #     "SELECT COUNT(*) FROM processing_batches").fetchone()
                        session.execute(
                            text("SELECT COUNT(*) FROM processing_batches")).fetchone()
                    except Exception as table_error:
                        logger.warning(f"Table access error: {table_error}")
                        error_details = "Database tables not initialized"
                        raise  # Re-raise to be caught by outer exception

                    database_status = "connected"
                    logger.info("Database connection verified successfully")

                except Exception as db_error:
                    error_msg = str(db_error).lower()
                    if "connection" in error_msg:
                        error_details = "Cannot connect to database server"
                    elif "authentication" in error_msg:
                        error_details = "Database authentication failed"
                    elif "relation" in error_msg:
                        error_details = "Required tables not found"
                    else:
                        error_details = f"Database error: {str(db_error)}"

                    logger.error(f"Database check failed: {error_details}")
                    logger.debug(f"Full error: {db_error}", exc_info=True)

                finally:
                    session.close()

            except Exception as session_error:
                error_details = f"Session creation failed: {str(session_error)}"
                logger.error(error_details)
                logger.debug("Session error details:", exc_info=True)

            # Redis status
            try:
                job_queue.redis_client.ping()
                redis_status = "connected"
            except:
                redis_status = "error"

            return render_template('modern_system_status.html',
                                   system_stats=system_stats,
                                   database_status=database_status,
                                   redis_status=redis_status,
                                   error_details=error_details,
                                   config=config)

        except Exception as e:
            logger.error(f"Error loading system status: {e}")
            return render_template('error.html',
                                   error="Could not load system status"), 500

    # Administrative endpoints for managing stuck jobs
    @app.route('/admin/queue/status')
    def admin_queue_status():
        """Get queue status including stuck jobs"""
        try:
            # Workaround: Implement queue status directly
            from .job_queue import job_queue
            import redis
            import json

            queue_stats = job_queue.get_queue_stats()

            # Analyze stuck jobs
            r = redis.Redis(host='localhost', port=6379, db=0)
            queue_name = job_queue.queue_name
            stuck_jobs = []

            try:
                job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))
                for job_key in job_keys:
                    job_data = r.get(job_key)
                    if job_data:
                        job_info = json.loads(job_data)
                        if job_info.get('job_type') == 'process_chunk':
                            stuck_jobs.append({
                                'job_id': job_info.get('job_id'),
                                'job_type': job_info.get('job_type'),
                                'status': job_info.get('status'),
                                'retry_count': job_info.get('retry_count', 0),
                                'batch_id': job_info.get('batch_id'),
                                'created_at': job_info.get('created_at')
                            })
            except Exception as e:
                logger.warning(f"Could not analyze stuck jobs: {e}")

            queue_status = {
                'queue_stats': queue_stats,
                'total_stuck': len(stuck_jobs),
                'stuck_jobs': stuck_jobs,
                'recommendations': [f"Remove {len(stuck_jobs)} jobs with invalid type 'process_chunk'"] if stuck_jobs else []
            }

            return jsonify({
                'success': True,
                'data': queue_status
            })
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/queue/cleanup', methods=['POST'])
    def admin_cleanup_queue():
        """Clean up stuck jobs in the queue and database"""
        try:
            data = request.get_json() or {}
            job_types = data.get(
                'job_types', ['process_chunk', 'chunk_processing'])
            max_age_hours = data.get('max_age_hours', 24)
            clean_database = data.get('clean_database', True)

            # Workaround: Implement cleanup directly
            from .job_queue import job_queue
            import redis
            import json
            from datetime import datetime, timedelta

            r = redis.Redis(host='localhost', port=6379, db=0)
            queue_name = job_queue.queue_name

            redis_removed_count = 0
            db_reset_count = 0
            kept_count = 0
            removed_types = set()
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)

            # 1. Clean Redis jobs
            job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))

            for job_key in job_keys:
                job_data = r.get(job_key)
                if job_data:
                    job_info = json.loads(job_data)
                    job_type = job_info.get('job_type')

                    should_remove = False

                    # Remove if job type is in removal list
                    if job_type in job_types:
                        should_remove = True
                        removed_types.add(job_type)

                    if should_remove:
                        # Remove from Redis
                        r.delete(job_key)
                        # Also remove from sorted set queue
                        r.zrem(queue_name, job_info.get('job_id'))
                        redis_removed_count += 1
                        logger.info(
                            f"Removed stuck Redis job {job_info.get('job_id')} of type {job_type}")
                    else:
                        kept_count += 1

            # 2. Clean database records if requested
            if clean_database:
                try:
                    from .database_models import db_manager, ProcessingBatch, ProcessingChunk, BatchStatus, ChunkStatus

                    # Reset stuck batches older than max_age_hours
                    # Use timezone-aware datetime for proper comparison
                    from datetime import timezone
                    cutoff_timestamp = datetime.now(
                        timezone.utc) - timedelta(hours=max_age_hours)

                    logger.info(
                        f"Database cleanup: looking for batches older than {cutoff_timestamp}")

                    with db_manager.get_session() as session:
                        # Find stuck batches (PENDING or QUEUED for too long)
                        from sqlalchemy import or_
                        stuck_batches = session.query(ProcessingBatch).filter(
                            or_(
                                ProcessingBatch.status == BatchStatus.PENDING,
                                ProcessingBatch.status == BatchStatus.QUEUED,
                                ProcessingBatch.status == BatchStatus.PROCESSING
                            ),
                            ProcessingBatch.created_at < cutoff_timestamp
                        ).all()

                        logger.info(
                            f"Found {len(stuck_batches)} stuck batches to clean")

                        cleaned_batches = []
                        for batch in stuck_batches:
                            logger.info(
                                f"Cleaning batch {batch.batch_name} (created: {batch.created_at})")
                            batch.status = BatchStatus.CANCELLED
                            batch.updated_at = datetime.now(timezone.utc)
                            batch.error_message = 'Cleaned up by admin - stuck for too long'
                            cleaned_batches.append(
                                (batch.batch_id, batch.batch_name))

                        # Reset their chunks too
                        if cleaned_batches:
                            batch_ids = [batch_id for batch_id,
                                         _ in cleaned_batches]
                            stuck_chunks = session.query(ProcessingChunk).filter(
                                ProcessingChunk.batch_id.in_(batch_ids),
                                or_(
                                    ProcessingChunk.status == ChunkStatus.PENDING,
                                    ProcessingChunk.status == ChunkStatus.PROCESSING
                                )
                            ).all()

                            logger.info(
                                f"Found {len(stuck_chunks)} stuck chunks to clean")

                            for chunk in stuck_chunks:
                                chunk.status = ChunkStatus.FAILED
                                chunk.updated_at = datetime.now(timezone.utc)
                                chunk.error_message = 'Batch cleaned up by admin'

                        session.commit()
                        db_reset_count = len(cleaned_batches)

                        for batch_id, batch_name in cleaned_batches:
                            logger.info(
                                f"Reset stuck batch {batch_name} ({batch_id}) to CANCELLED")

                except Exception as db_error:
                    logger.error(f"Database cleanup error: {db_error}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")

            result = {
                'redis_removed_count': redis_removed_count,
                'db_reset_count': db_reset_count,
                'kept_count': kept_count,
                'removed_types': list(removed_types),
                'cutoff_hours': max_age_hours,
                'clean_database': clean_database
            }

            return jsonify({
                'success': True,
                'data': result
            })
        except Exception as e:
            logger.error(f"Error cleaning up queue: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/reset', methods=['POST'])
    def admin_reset_batch(batch_id):
        """Reset a stuck batch back to PENDING status"""
        try:
            # Safely get JSON data with fallback to empty dict
            data = request.get_json(force=False, silent=True)
            if data is None:
                data = {}

            force = data.get('force', False)

            result = batch_manager.reset_stuck_batch(batch_id, force=force)

            return jsonify({
                'success': result.get('success', True),
                'data': result
            })
        except Exception as e:
            logger.error(f"Error resetting batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/start', methods=['POST'])
    def admin_start_batch(batch_id):
        """Start a batch"""
        try:
            # Use the batch manager to start processing
            result = batch_manager.start_batch_processing(batch_id)
            if result:
                return jsonify({
                    'success': True,
                    'message': 'Batch started successfully'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Failed to start batch'
                }), 400
        except Exception as e:
            logger.error(f"Error starting batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/pause', methods=['POST'])
    def admin_pause_batch(batch_id):
        """Pause a batch"""
        try:
            # Use the existing batch pause logic
            return redirect(url_for('pause_batch', batch_id=batch_id))
        except Exception as e:
            logger.error(f"Error pausing batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/resume', methods=['POST'])
    def admin_resume_batch(batch_id):
        """Resume a batch"""
        try:
            # Use the existing batch resume logic
            return redirect(url_for('resume_batch', batch_id=batch_id))
        except Exception as e:
            logger.error(f"Error resuming batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/cancel', methods=['POST'])
    def admin_cancel_batch(batch_id):
        """Cancel a batch"""
        try:
            # Use the existing batch cancel logic
            return redirect(url_for('cancel_batch', batch_id=batch_id))
        except Exception as e:
            logger.error(f"Error cancelling batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/batch/<batch_id>/retry', methods=['POST'])
    def admin_retry_batch(batch_id):
        """Retry a batch"""
        try:
            # Use the existing batch retry logic
            return redirect(url_for('retry_batch', batch_id=batch_id))
        except Exception as e:
            logger.error(f"Error retrying batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/job/<job_id>/retry', methods=['POST'])
    def admin_retry_job(job_id):
        """Retry a specific job"""
        try:
            # In this context, job_id could be a batch_id or chunk_id
            # For simplicity, we'll assume it's a batch_id and reset it to retry
            data = request.get_json() or {}

            # Try to reset the batch to retry it
            try:
                result = batch_manager.reset_stuck_batch(job_id, force=True)
                return jsonify({
                    'success': True,
                    'data': result,
                    'message': f'Batch {job_id} reset and queued for retry'
                })
            except Exception as batch_error:
                # If batch reset fails, return error
                logger.warning(
                    f"Could not retry batch {job_id}: {batch_error}")
                return jsonify({
                    'success': False,
                    'error': f'Job {job_id} could not be retried: {str(batch_error)}'
                }), 400

        except Exception as e:
            logger.error(f"Error retrying job {job_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin/job/<job_id>', methods=['DELETE'])
    def admin_delete_job(job_id):
        """Delete a specific job"""
        try:
            # In this context, job_id could be a batch_id
            # For simplicity, we'll assume it's a batch_id and try to cancel it
            data = request.get_json() or {}
            force = data.get('force', False)

            try:
                result = batch_manager.cancel_batch(job_id)
                return jsonify({
                    'success': True,
                    'data': result,
                    'message': f'Job {job_id} cancelled successfully'
                })
            except Exception as cancel_error:
                logger.warning(
                    f"Could not cancel job {job_id}: {cancel_error}")
                return jsonify({
                    'success': False,
                    'error': f'Job {job_id} could not be cancelled: {str(cancel_error)}'
                }), 400

        except Exception as e:
            logger.error(f"Error deleting job {job_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/admin')
    def admin_dashboard():
        """Administrative dashboard"""
        try:
            # Workaround: Implement queue status directly until class loading is fixed
            from .job_queue import job_queue
            import redis
            import json

            logger.info("Loading admin dashboard...")

            # Get basic queue stats with fallback values
            try:
                queue_stats = job_queue.get_queue_stats()
                logger.info(f"Queue stats retrieved: {queue_stats}")
                # Ensure all required keys exist with default values
                queue_stats = {
                    'pending': queue_stats.get('pending', 0),
                    'processing': queue_stats.get('processing', 0),
                    'retrying': queue_stats.get('retrying', 0),
                    'completed': queue_stats.get('completed', 0),
                    'failed': queue_stats.get('failed', 0)
                }
                logger.info(f"Processed queue stats: {queue_stats}")
            except Exception as e:
                logger.error(f"Could not get queue stats: {e}")
                queue_stats = {
                    'pending': 0,
                    'processing': 0,
                    'retrying': 0,
                    'completed': 0,
                    'failed': 0
                }

            # Get stuck jobs analysis
            stuck_jobs = []
            try:
                r = redis.Redis(host='localhost', port=6379, db=0)
                queue_name = job_queue.queue_name
                job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))
                for job_key in job_keys:
                    job_data = r.get(job_key)
                    if job_data:
                        job_info = json.loads(job_data)
                        # Consider jobs stuck if they have invalid types
                        if job_info.get('job_type') == 'process_chunk':
                            stuck_jobs.append({
                                'job_id': job_info.get('job_id'),
                                'job_type': job_info.get('job_type'),
                                'status': job_info.get('status'),
                                'retry_count': job_info.get('retry_count', 0),
                                'batch_id': job_info.get('batch_id'),
                                'created_at': job_info.get('created_at')
                            })
                logger.info(f"Found {len(stuck_jobs)} stuck jobs")
            except Exception as e:
                logger.error(f"Could not analyze stuck jobs: {e}")

            # Generate recommendations
            recommendations = []
            if stuck_jobs:
                recommendations.append(
                    f"Remove {len(stuck_jobs)} jobs with invalid type 'process_chunk'")
            elif sum(queue_stats.values()) == 0:
                recommendations.append("No jobs in queue - system is idle")
            else:
                recommendations.append("Queue is operating normally")

            queue_status = {
                'queue_stats': queue_stats,
                'total_stuck': len(stuck_jobs),
                'stuck_jobs': stuck_jobs,
                'recommendations': recommendations
            }
            logger.info(f"Queue status prepared: {queue_status}")

            # Get system stats with better error handling
            try:
                logger.info("Getting batch summary stats...")
                batch_stats = batch_manager.get_batch_summary_stats()
                logger.info(f"Batch stats retrieved: {batch_stats}")

                # Map the fields to match template expectations
                system_stats = {
                    'total_batches': batch_stats.get('total_batches', 0),
                    'active_batches': batch_stats.get('active_batches', 0),
                    'completed_batches': batch_stats.get('completed_batches', 0),
                    'total_processed': batch_stats.get('total_urls_processed', 0),
                    'average_success_rate': batch_stats.get('overall_success_rate', 0.0)
                }
                logger.info(f"System stats prepared: {system_stats}")
            except Exception as e:
                logger.error(f"Could not get system stats: {e}")
                logger.exception("Full exception details:")
                system_stats = {
                    'total_batches': 0,
                    'active_batches': 0,
                    'completed_batches': 0,
                    'total_processed': 0,
                    'average_success_rate': 0.0
                }

            logger.info("Rendering admin dashboard template...")
            return render_template('modern_admin_dashboard.html',
                                   queue_status=queue_status,
                                   system_stats=system_stats)
        except Exception as e:
            logger.error(f"Error loading admin dashboard: {e}")
            logger.exception("Full exception details:")
            return render_template('error.html',
                                   error="Could not load admin dashboard"), 500

    @app.route('/admin/debug')
    def admin_debug():
        """Debug endpoint to check queue status data"""
        try:
            from .job_queue import job_queue
            queue_stats = job_queue.get_queue_stats()

            return jsonify({
                'success': True,
                'queue_stats': queue_stats,
                'raw_data': str(queue_stats),
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })

    # API endpoints
    @app.route('/api/v1/batches')
    def api_list_batches():
        """API endpoint to list all batches with pagination"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            status_filter = request.args.get('status', None)
            include_soft_deleted = request.args.get(
                'include_soft_deleted', 'false').lower() == 'true'

            # Get paginated batches
            batches_info = batch_manager.get_all_batches(
                page=page,
                per_page=per_page,
                status_filter=status_filter,
                include_soft_deleted=include_soft_deleted
            )

            return jsonify({
                'success': True,
                'data': {
                    'batches': batches_info
                },
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'has_next': len(batches_info) == per_page,
                    'total_returned': len(batches_info)
                }
            })
        except Exception as e:
            logger.error(f"Error listing batches: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/system/stats')
    def api_system_stats():
        """API endpoint for system statistics"""
        try:
            system_stats = batch_manager.get_batch_summary_stats()
            return jsonify({
                'success': True,
                'data': system_stats
            })
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/queue/status')
    def api_queue_status():
        """API endpoint for queue status"""
        try:
            from .job_queue import job_queue

            # Get queue statistics
            queue_stats = {
                'pending': 0,
                'processing': 0,
                'completed': 0,
                'failed': 0
            }

            try:
                r = redis.Redis(host='localhost', port=6379, db=0)
                queue_name = job_queue.queue_name

                # Count jobs by status
                job_keys = list(r.scan_iter(match=f"{queue_name}:job:*"))
                for job_key in job_keys:
                    job_data = r.get(job_key)
                    if job_data:
                        job_info = json.loads(job_data)
                        status = job_info.get('status', 'pending')
                        if status in queue_stats:
                            queue_stats[status] += 1
                        else:
                            queue_stats['pending'] += 1

            except Exception as e:
                logger.warning(f"Could not get detailed queue stats: {e}")

            return jsonify({
                'success': True,
                'data': queue_stats
            })
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batches/stuck')
    def api_stuck_batches():
        """API endpoint for stuck batches"""
        try:
            # Get all batches and filter for stuck ones
            all_batches = batch_manager.list_batches(limit=50)
            stuck_batches = []

            for batch in all_batches:
                # Consider batches stuck if they're in PROCESSING status for too long
                # or have been QUEUED for an extended period
                if batch.status in ['PROCESSING', 'QUEUED']:
                    if hasattr(batch, 'started_at') and batch.started_at:
                        from datetime import datetime, timezone
                        time_diff = datetime.now(
                            timezone.utc) - batch.started_at
                        if time_diff.total_seconds() > 3600:  # 1 hour
                            stuck_batches.append({
                                'batch_id': batch.batch_id,
                                'batch_name': batch.batch_name,
                                'status': batch.status.value if hasattr(batch.status, 'value') else str(batch.status),
                                'total_urls': batch.total_urls,
                                'processed_count': batch.processed_count,
                                'progress_percentage': (batch.processed_count / batch.total_urls * 100) if batch.total_urls > 0 else 0,
                                'started_at': batch.started_at.isoformat() if batch.started_at else None,
                                'created_at': batch.created_at.isoformat() if batch.created_at else None
                            })

            return jsonify({
                'success': True,
                'data': stuck_batches
            })
        except Exception as e:
            logger.error(f"Error getting stuck batches: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batch/<batch_id>', methods=['GET'])
    def api_get_batch(batch_id):
        """API endpoint to get specific batch details"""
        try:
            # Use the batch manager to get batch details
            batch_info = batch_manager.get_batch_details(batch_id)

            if not batch_info:
                # If batch not found, return 404 with a clear error message
                logger.warning(
                    f"API request for non-existent batch: {batch_id}")
                return jsonify({
                    'success': False,
                    'error': 'Batch not found',
                    'id': batch_id
                }), 404

            # Return 200 OK with batch data
            return jsonify({
                'success': True,
                'data': batch_info
            })

        except Exception as e:
            # Log the full error for debugging
            logger.error(
                f"Error getting batch {batch_id} via API: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'An internal error occurred',
                'details': str(e)
            }), 500

    @app.route('/api/v1/batches/<batch_id>/results')
    def api_get_batch_results(batch_id):
        """API endpoint to get batch results with filtering"""
        try:
            status_filter = request.args.get('status')

            # Get batch results from batch manager
            results = batch_manager.get_batch_results(batch_id, status_filter)

            if results is None:
                return jsonify({
                    'success': False,
                    'error': 'Batch not found'
                }), 404

            return jsonify({
                'success': True,
                'data': results
            })
        except Exception as e:
            logger.error(f"Error getting batch results for {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batches/<batch_id>', methods=['DELETE'])
    def api_delete_batch(batch_id):
        """API endpoint to delete a batch"""
        try:
            # Use the batch manager to delete the batch
            result = batch_manager.delete_batch(batch_id)

            if not result.get('success', False):
                return jsonify({
                    'success': False,
                    'error': result.get('error', 'Failed to delete batch')
                }), 400

            return jsonify({
                'success': True,
                'message': 'Batch deleted successfully'
            })
        except Exception as e:
            logger.error(f"Error deleting batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batches/<batch_id>/export')
    def api_export_batch(batch_id):
        """API endpoint to export batch results"""
        try:
            # Use the export manager to export results
            export_path = export_manager.export_batch_results(batch_id)

            if not export_path:
                return jsonify({
                    'success': False,
                    'error': 'Failed to export batch or batch not found'
                }), 404

            # Serve the file for download
            return send_file(export_path, as_attachment=True, download_name=f'batch_{batch_id}_results.csv')
        except Exception as e:
            logger.error(f"Error exporting batch {batch_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batch-data', methods=['GET'])
    def api_get_batch_data():
        """API endpoint to get batch data with filtering, pagination, and sorting"""
        try:
            from .database_models import URLAnalysisResult
            from sqlalchemy import asc, desc, and_, String

            # Get query parameters
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 25, type=int)
            success_filter = request.args.get('success', 'all')
            store_image_filter = request.args.get('store_image', 'all')
            batch_id_filter = request.args.get('batch_id', '')
            sort_param = request.args.get('sort', 'created_at:desc')

            # Validate pagination
            page = max(1, page)
            per_page = min(max(1, per_page), 1000)  # Cap at 1000 rows per page

            # Parse sort parameter
            sort_parts = sort_param.split(':')
            sort_field = sort_parts[0] if sort_parts[0] in [
                'success', 'store_image', 'store_name', 'processing_time_seconds', 'created_at'] else 'created_at'
            sort_dir = sort_parts[1] if len(sort_parts) > 1 and sort_parts[1] in [
                'asc', 'desc'] else 'desc'

            # Build query
            with db_manager.get_session() as session:
                query = session.query(URLAnalysisResult)

                # Apply filters
                filters = []

                # Success filter
                if success_filter == 'true':
                    filters.append(URLAnalysisResult.success == True)
                elif success_filter == 'false':
                    filters.append(URLAnalysisResult.success == False)

                # Store image filter
                if store_image_filter == 'true':
                    filters.append(URLAnalysisResult.store_image == True)
                elif store_image_filter == 'false':
                    filters.append(URLAnalysisResult.store_image == False)

                # Batch ID filter
                if batch_id_filter:
                    import uuid
                    try:
                        batch_id_obj = uuid.UUID(batch_id_filter)
                        filters.append(
                            URLAnalysisResult.batch_id == batch_id_obj)
                    except ValueError:
                        filters.append(URLAnalysisResult.batch_id.cast(
                            String).ilike(f'%{batch_id_filter}%'))

                # Apply all filters
                if filters:
                    query = query.filter(and_(*filters))

                # Get total count
                total_count = query.count()

                # Apply sorting
                sort_column = getattr(URLAnalysisResult, sort_field)
                query = query.order_by(
                    asc(sort_column) if sort_dir == 'asc' else desc(sort_column))

                # Apply pagination
                results = query.offset(
                    (page - 1) * per_page).limit(per_page).all()

                # Convert to dictionaries
                data = []
                for result in results:
                    data.append({
                        'success': result.success,
                        'store_image': result.store_image,
                        'text_content': result.text_content,
                        'store_name': result.store_name,
                        'business_contact': result.business_contact,
                        'image_description': result.image_description,
                        'url': result.url,
                        'processing_time_seconds': result.processing_time_seconds,
                        'created_at': result.created_at.isoformat() if result.created_at else None,
                        'batch_id': str(result.batch_id) if result.batch_id else None
                    })

                return jsonify({
                    'data': data,
                    'meta': {
                        'page': page,
                        'per_page': per_page,
                        'total': total_count
                    }
                }), 200

        except Exception as e:
            logger.error(f"Error fetching batch data: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    @app.route('/api/v1/batch-data/export', methods=['GET'])
    def api_export_batch_data():
        """API endpoint to export batch data as CSV with streaming"""
        try:
            from .database_models import URLAnalysisResult
            from sqlalchemy import and_, String
            import csv
            import io

            # Get query parameters (same as list endpoint)
            success_filter = request.args.get('success', 'all')
            store_image_filter = request.args.get('store_image', 'all')
            batch_id_filter = request.args.get('batch_id', '')

            # Build query
            with db_manager.get_session() as session:
                query = session.query(URLAnalysisResult)

                # Apply filters
                filters = []

                # Success filter
                if success_filter == 'true':
                    filters.append(URLAnalysisResult.success == True)
                elif success_filter == 'false':
                    filters.append(URLAnalysisResult.success == False)

                # Store image filter
                if store_image_filter == 'true':
                    filters.append(URLAnalysisResult.store_image == True)
                elif store_image_filter == 'false':
                    filters.append(URLAnalysisResult.store_image == False)

                # Batch ID filter
                if batch_id_filter:
                    import uuid
                    try:
                        batch_id_obj = uuid.UUID(batch_id_filter)
                        filters.append(
                            URLAnalysisResult.batch_id == batch_id_obj)
                    except ValueError:
                        filters.append(URLAnalysisResult.batch_id.cast(
                            String).ilike(f'%{batch_id_filter}%'))

                # Apply all filters
                if filters:
                    query = query.filter(and_(*filters))

                # Order by created_at descending
                query = query.order_by(URLAnalysisResult.created_at.desc())

                # Get results
                results = query.all()

                # Create CSV buffer
                csv_buffer = io.StringIO()
                writer = csv.writer(csv_buffer)

                # Write header
                headers = ['success', 'store_front', 'text_content', 'store_name', 'business_contact',
                           'image_description', 'url', 'processing_time_seconds', 'created_at', 'batch_id']
                writer.writerow(headers)

                # Write data rows
                for result in results:
                    writer.writerow([
                        'true' if result.success else 'false',
                        'true' if result.store_image else 'false',
                        result.text_content or '',
                        result.store_name or '',
                        result.business_contact or '',
                        result.image_description or '',
                        result.url or '',
                        result.processing_time_seconds or '',
                        result.created_at.isoformat() if result.created_at else '',
                        str(result.batch_id) if result.batch_id else ''
                    ])

                # If no results, just return header
                if not results:
                    writer.writerow([])

                # Create response
                csv_data = csv_buffer.getvalue()
                response = make_response(csv_data)
                response.headers['Content-Type'] = 'text/csv; charset=utf-8'
                response.headers['Content-Disposition'] = 'attachment; filename="batch-data-export.csv"'

                return response

        except Exception as e:
            logger.error(f"Error exporting batch data: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # Legacy routes for backward compatibility    # Legacy routes for backward compatibility
    @app.route('/legacy/analyze', methods=['POST'])
    def legacy_analyze():
        """Legacy single URL analysis endpoint"""
        try:
            # Use original analyzer if available
            if hasattr(app, 'analyzer'):
                # Implementation would go here for single URL processing
                return jsonify({
                    'success': False,
                    'error': 'Legacy single URL analysis not implemented in enterprise version'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'Legacy analyzer not available'
                }), 503

        except Exception as e:
            logger.error(f"Error in legacy analyze: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/v1/results/<result_id>/retry', methods=['POST'])
    def api_retry_result(result_id):
        """API endpoint to retry a specific failed result"""
        try:
            # Get the result from database
            with db_manager.get_session() as session:
                from .database_models import URLAnalysisResult
                result = session.query(URLAnalysisResult).filter_by(
                    id=result_id).first()

                if not result:
                    return jsonify({
                        'success': False,
                        'error': 'Result not found'
                    }), 404

                if result.success:
                    return jsonify({
                        'success': False,
                        'error': 'Cannot retry successful result'
                    }), 400

                # Add the URL back to the job queue for retry
                job_data = {
                    'url': result.url,
                    'batch_id': result.batch_id,
                    'chunk_id': result.chunk_id,
                    'retry': True,
                    'original_result_id': result_id
                }

                job_queue.add_job(job_data)

                return jsonify({
                    'success': True,
                    'message': 'URL queued for retry'
                })

        except Exception as e:
            logger.error(f"Error retrying result {result_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return render_template('error.html', error="Page not found"), 404

    @app.errorhandler(500)
    def server_error(error):
        logger.error(f"Server error: {error}")
        return render_template('error.html', error="Internal server error"), 500

    @app.errorhandler(413)
    def file_too_large(error):
        return jsonify({
            'success': False,
            'error': f'File too large. Maximum size: {config.max_upload_size // (1024*1024)}MB'
        }), 413

    # Shutdown handler
    def shutdown_handler(signum, frame):
        """Handle graceful shutdown"""
        logger.info("Shutting down enterprise application...")

        try:
            # Stop background workers
            job_queue.stop()

            # Close database connections
            db_manager.close()

            logger.info("Shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        sys.exit(0)

    # Register shutdown handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    return app


# Create the enterprise application
enterprise_app = create_enterprise_app()


if __name__ == '__main__':
    """Run the enterprise application"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Enterprise Image Processing Application")
    parser.add_argument('--host', default='127.0.0.1',
                        help='Host to bind to (use 0.0.0.0 for production)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to bind to')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode')
    parser.add_argument('--workers', type=int, default=None,
                        help='Number of background workers')

    args = parser.parse_args()

    logger.info("="*80)
    logger.info("ENTERPRISE IMAGE PROCESSING APPLICATION")
    logger.info("="*80)
    logger.info(f"Host: {args.host}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Debug: {args.debug}")
    logger.info(f"Max Upload Size: {config.max_upload_size // (1024*1024)}MB")
    logger.info(f"Chunk Size: {config.chunk_size}")
    logger.info(f"Max Concurrent Batches: {config.max_concurrent_batches}")
    logger.info("="*80)

    try:
        enterprise_app.run(
            host=args.host,
            port=args.port,
            debug=args.debug,
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)
