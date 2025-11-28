"""
Polling API endpoints for batch processing status and progress
"""
from flask import Flask, request, jsonify, Blueprint
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.batch_manager import batch_manager
from src.job_queue import job_queue
from flask import Response, stream_with_context
import time
import json
from src.database_models import BatchStatus
from src.enterprise_config import config

logger = logging.getLogger(__name__)

# Create Blueprint for polling API
polling_api = Blueprint('polling_api', __name__, url_prefix='/api/v1')


@polling_api.route('/ping', methods=['GET'])
def ping():
    """Lightweight liveness probe that does not touch DB/Redis"""
    return jsonify({
        'success': True,
        'data': {
            'status': 'ok',
        },
        'timestamp': datetime.now().isoformat()
    })


@polling_api.route('/batches', methods=['GET'])
def list_batches():
    """List all batches with optional filtering"""
    try:
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        status_filter = request.args.get('status')

        # Validate limit
        if limit > 100:
            limit = 100

        batches = batch_manager.list_batches(
            limit=limit, status_filter=status_filter)

        return jsonify({
            'success': True,
            'data': {
                'batches': batches,
                'count': len(batches),
                'limit': limit,
                'status_filter': status_filter
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error listing batches: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/status', methods=['GET'])
def get_batch_status(batch_id: str):
    """Get detailed status for a specific batch"""
    try:
        status = batch_manager.get_batch_status(batch_id)

        return jsonify({
            'success': True,
            'data': status,
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        # If a batch with this ID doesn't exist it *might* be a parent_batch_id
        # (created when a large CSV was split into multiple batches). In that
        # situation, return an aggregated status for the parent to keep the
        # response shape consistent for clients that expect a 'progress' object.
        try:
            # Attempt to fetch parent aggregated status via BatchManager
            parent_status = batch_manager.get_parent_batch_status(batch_id)

            # Map parent aggregated payload into the same shape as a
            # per-batch get_batch_status result so UI code can read the same
            # fields without defensive checks.
            status_like = {
                'batch_id': batch_id,
                'status': parent_status.get('overall_status', 'unknown'),
                'created_at': parent_status.get('started_at'),
                'chunk_statistics': {},
                'processing_rate': None,
                'estimated_completion': parent_status.get('completed_at'),
                'recent_errors': [],
                'progress': {
                    'progress_percentage': parent_status.get('progress_percentage', 0),
                    'total_urls': parent_status.get('total_urls', 0),
                    'processed_count': parent_status.get('processed_count', 0),
                    'successful_count': parent_status.get('successful_count', 0),
                    'failed_count': parent_status.get('failed_count', 0),
                },
                'batch_info': {
                    'batch_name': f"Parent:{parent_status.get('parent_batch_id')}",
                    'status': parent_status.get('overall_status', 'unknown'),
                    'is_active': parent_status.get('overall_status') in ['processing', 'queued'],
                    'batch_id': parent_status.get('parent_batch_id'),
                    'total_urls': parent_status.get('total_urls', 0),
                    'processed_count': parent_status.get('processed_count', 0),
                    'created_at': parent_status.get('started_at')
                },
                'timing': {
                    'started_at': parent_status.get('started_at'),
                    'completed_at': parent_status.get('completed_at'),
                    'elapsed_time_minutes': None,
                    'remaining_time_minutes': None,
                    'estimated_completion': parent_status.get('completed_at')
                },
                'performance': {
                    'processing_rate_per_minute': None,
                    'success_rate_percentage': round(parent_status.get('successful_count', 0) / max(parent_status.get('processed_count', 1), 1) * 100, 2) if parent_status.get('processed_count', 0) > 0 else 0
                }
            }

            return jsonify({
                'success': True,
                'data': status_like,
                'timestamp': datetime.now().isoformat()
            })

        except Exception:
            return jsonify({
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 404

    except Exception as e:
        logger.error(f"Error getting batch status for {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/progress', methods=['GET'])
def get_batch_progress(batch_id: str):
    """Get lightweight progress information for a batch"""
    try:
        status = batch_manager.get_batch_status(batch_id)

        # Some batch_id values may represent a parent batch (CSV-split parent) which
        # returns an aggregated payload via get_parent_batch_status() instead of the
        # regular per-batch get_batch_status() shape. Be defensive here and map
        # a parent-style response into the same progress structure so callers don't
        # experience `undefined` errors when reading fields like total_urls.

        # If this is a normal per-batch payload, use the nested progress object.
        if status and isinstance(status.get('progress'), dict):
            progress = status.get('progress', {})
            batch_info = status.get('batch_info', {})

            progress_data = {
                'batch_id': batch_id,
                'status': batch_info.get('status', 'unknown'),
                'progress_percentage': progress.get('progress_percentage', 0),
                'processed_count': progress.get('processed_count', 0),
                'total_urls': progress.get('total_urls', 0),
                'successful_count': progress.get('successful_count', 0),
                'failed_count': progress.get('failed_count', 0),
                'current_chunk': progress.get('current_chunk'),
                'total_chunks': progress.get('total_chunks'),
                'estimated_completion': status.get('timing', {}).get('estimated_completion'),
                'processing_rate_per_minute': status.get('performance', {}).get('processing_rate_per_minute'),
                'is_active': batch_info.get('is_active', False)
            }
        else:
            # Possibly a parent batch - try aggregating status across the group
            try:
                parent_status = batch_manager.get_parent_batch_status(batch_id)
                progress_data = {
                    'batch_id': batch_id,
                    'status': parent_status.get('overall_status', 'unknown'),
                    'progress_percentage': parent_status.get('progress_percentage', 0),
                    'processed_count': parent_status.get('processed_count', 0),
                    'total_urls': parent_status.get('total_urls', 0),
                    'successful_count': parent_status.get('successful_count', 0),
                    'failed_count': parent_status.get('failed_count', 0),
                    'current_chunk': None,
                    'total_chunks': parent_status.get('total_chunks'),
                    'estimated_completion': parent_status.get('completed_at'),
                    'processing_rate_per_minute': None,
                    'is_active': parent_status.get('overall_status') in ['processing', 'queued']
                }
            except Exception:
                # If nothing works, return a safe, default progress shape
                progress_data = {
                    'batch_id': batch_id,
                    'status': 'unknown',
                    'progress_percentage': 0,
                    'processed_count': 0,
                    'total_urls': 0,
                    'successful_count': 0,
                    'failed_count': 0,
                    'current_chunk': None,
                    'total_chunks': None,
                    'estimated_completion': None,
                    'processing_rate_per_minute': None,
                    'is_active': False
                }

        return jsonify({
            'success': True,
            'data': progress_data,
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 404

    except Exception as e:
        logger.error(f"Error getting batch progress for {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches', methods=['POST'])
def create_batch():
    """Create a new batch from uploaded CSV"""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded',
                'timestamp': datetime.now().isoformat()
            }), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected',
                'timestamp': datetime.now().isoformat()
            }), 400

        # Get optional batch name and auto-start preference
        batch_name = request.form.get('batch_name')
        # Default to auto-start for consistent behavior (matches web form)
        auto_start = request.form.get('auto_start', 'true').lower() == 'true'

        # Read CSV content
        csv_content = file.read().decode('utf-8')

        # Create batch
        batch_id, batch_info = batch_manager.create_batch_from_csv(
            csv_content=csv_content,
            batch_name=batch_name,
            filename=file.filename
        )

        # Auto-start the batch (consistent with web form behavior)
        if auto_start:
            try:
                batch_manager.start_batch_processing(batch_id)
                batch_info['auto_started'] = True
                batch_info['status'] = 'QUEUED'
            except Exception as e:
                logger.warning(f"Could not auto-start batch {batch_id}: {e}")
                batch_info['auto_start_error'] = str(e)
                batch_info['auto_started'] = False

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'batch_info': batch_info
            },
            'message': 'Batch created and processing started' if auto_start and batch_info.get('auto_started') else 'Batch created successfully',
            'timestamp': datetime.now().isoformat()
        }), 201

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error creating batch: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/start', methods=['POST'])
def start_batch(batch_id: str):
    """Start processing a batch"""
    try:
        success = batch_manager.start_batch_processing(batch_id)

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'started': success
            },
            'message': f'Batch {batch_id} processing started',
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error starting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/pause', methods=['POST'])
def pause_batch(batch_id: str):
    """Pause batch processing"""
    try:
        success = batch_manager.pause_batch(batch_id)

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'paused': success
            },
            'message': f'Batch {batch_id} processing paused',
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error pausing batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/resume', methods=['POST'])
def resume_batch(batch_id: str):
    """Resume paused batch processing"""
    try:
        success = batch_manager.resume_batch(batch_id)

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'resumed': success
            },
            'message': f'Batch {batch_id} processing resumed',
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error resuming batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/cancel', methods=['POST'])
def cancel_batch(batch_id: str):
    """Cancel batch processing"""
    try:
        success = batch_manager.cancel_batch(batch_id)

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'cancelled': success
            },
            'message': f'Batch {batch_id} processing cancelled',
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error cancelling batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>', methods=['DELETE'])
def delete_batch(batch_id: str):
    """Delete a batch and all associated data"""
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        success = batch_manager.delete_batch(batch_id, force=force)

        return jsonify({
            'success': True,
            'data': {
                'batch_id': batch_id,
                'deleted': success
            },
            'message': f'Batch {batch_id} deleted',
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error deleting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/force-start', methods=['POST'])
def force_start_batch(batch_id: str):
    """Force start a batch regardless of current state"""
    try:
        data = request.get_json() or {}
        skip_validation = data.get('skip_validation', False)

        result = batch_manager.force_start_batch(
            batch_id, skip_validation=skip_validation)

        return jsonify({
            'success': True,
            'data': result,
            'message': result['message'],
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error force starting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/soft-delete', methods=['POST'])
def soft_delete_batch(batch_id: str):
    """Soft delete a batch (mark as deleted but preserve data)"""
    try:
        data = request.get_json() or {}
        retention_days = data.get('retention_days', 30)

        result = batch_manager.soft_delete_batch(
            batch_id, retention_days=retention_days)

        return jsonify({
            'success': True,
            'data': result,
            'message': result['message'],
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error soft deleting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/clone', methods=['POST'])
def clone_batch(batch_id: str):
    """Clone a batch with optional result copying"""
    try:
        data = request.get_json() or {}
        new_name = data.get('new_name')
        copy_results = data.get('copy_results', False)

        if not new_name:
            return jsonify({
                'success': False,
                'error': 'new_name parameter is required',
                'timestamp': datetime.now().isoformat()
            }), 400

        result = batch_manager.clone_batch(
            batch_id, new_name, copy_results=copy_results)

        return jsonify({
            'success': True,
            'data': result,
            'message': result['message'],
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error cloning batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batch/bulk/<action>', methods=['POST'])
@polling_api.route('/batches/bulk', methods=['POST'])
def bulk_batch_action(action: str = None):
    """Perform bulk operations on batches. Supported actions: delete, force-start, reset, soft-delete"""
    try:
        data = request.get_json() or {}

        # allow action in URL or payload
        action = action or data.get('action')

        if not action:
            return jsonify({'success': False, 'error': 'action is required (delete|force-start|reset|soft-delete)'}), 400

        batch_ids = data.get('batch_ids') or data.get('batchIds')
        if not batch_ids or not isinstance(batch_ids, list):
            return jsonify({'success': False, 'error': 'batch_ids (list) is required'}), 400

        action = action.lower()
        if action in ('delete', 'delete_batch', 'delete_batches'):
            force = data.get('force', False)
            result = batch_manager.delete_batches(batch_ids, force=force)

        elif action in ('force-start', 'forcestart', 'force_start'):
            skip_validation = data.get('skip_validation', False)
            result = batch_manager.force_start_batches(
                batch_ids, skip_validation=skip_validation)

        elif action in ('reset', 'reset_batch', 'reset_batches'):
            force = data.get('force', False)
            result = batch_manager.reset_batches(batch_ids, force=force)

        elif action in ('soft-delete', 'soft_delete'):
            retention_days = data.get('retention_days', 30)
            details = {}
            success_all = True
            deleted_count = 0
            for bid in batch_ids:
                try:
                    r = batch_manager.soft_delete_batch(
                        bid, retention_days=retention_days)
                    details[bid] = {'success': True, 'data': r}
                    deleted_count += 1
                except Exception as e:
                    details[bid] = {'success': False, 'error': str(e)}
                    success_all = False

            result = {
                'success': success_all,
                'details': details,
                'total': len(batch_ids),
                'soft_deleted': deleted_count
            }

        else:
            return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400

        return jsonify({'success': result.get('success', True), 'data': result})

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"Error performing bulk action {action}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@polling_api.route('/batches/<batch_id>/health', methods=['GET'])
def get_batch_health(batch_id: str):
    """Get batch health score and diagnostics"""
    try:
        result = batch_manager.get_batch_health_score(batch_id)

        return jsonify({
            'success': True,
            'data': result,
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error getting batch health {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/analyze', methods=['GET'])
def analyze_batch_errors(batch_id: str):
    """Analyze error patterns in a batch"""
    try:
        result = batch_manager.analyze_batch_errors(batch_id)

        return jsonify({
            'success': True,
            'data': result,
            'timestamp': datetime.now().isoformat()
        })

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error analyzing batch errors {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"Error deleting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/system/stats', methods=['GET'])
def get_system_stats():
    """Get overall system processing statistics"""
    try:
        stats = batch_manager.get_batch_summary_stats()

        return jsonify({
            'success': True,
            'data': stats,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/chunks', methods=['GET'])
def get_batch_chunks(batch_id: str):
    """Get chunk details for a batch"""
    try:
        from .database_models import ProcessingChunk, db_manager

        with db_manager.get_session() as session:
            chunks = session.query(ProcessingChunk).filter_by(batch_id=batch_id).order_by(
                ProcessingChunk.chunk_number
            ).all()

            if not chunks:
                return jsonify({
                    'success': False,
                    'error': f'No chunks found for batch {batch_id}',
                    'timestamp': datetime.now().isoformat()
                }), 404

            chunk_data = [
                {
                    'chunk_id': str(chunk.chunk_id),
                    'chunk_number': chunk.chunk_number,
                    'status': chunk.status.value,
                    'url_count': chunk.url_count,
                    'processed_count': chunk.processed_count,
                    'successful_count': chunk.successful_count,
                    'failed_count': chunk.failed_count,
                    'progress_percentage': chunk.progress_percentage,
                    'started_at': chunk.started_at.isoformat() if chunk.started_at else None,
                    'completed_at': chunk.completed_at.isoformat() if chunk.completed_at else None,
                    'processing_time_seconds': chunk.processing_time_seconds,
                    'error_message': chunk.error_message
                }
                for chunk in chunks
            ]

            return jsonify({
                'success': True,
                'data': {
                    'batch_id': batch_id,
                    'chunks': chunk_data,
                    'total_chunks': len(chunk_data)
                },
                'timestamp': datetime.now().isoformat()
            })

    except Exception as e:
        logger.error(f"Error getting chunks for batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        from src.database_models import db_manager
        from sqlalchemy import text
        with db_manager.get_session() as session:
            session.execute(text("SELECT 1")).fetchone()

        # Check Redis connection
        from src.job_queue import job_queue
        job_queue.redis_client.ping()

        return jsonify({
            'success': True,
            'data': {
                'status': 'healthy',
                'database': 'connected',
                'redis': 'connected',
                'config': {
                    'chunk_size': config.chunk_size,
                    'max_concurrent_batches': config.max_concurrent_batches,
                    'api_keys_count': len(config.api_keys_list)
                }
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat()
        }), 500


@polling_api.route('/batches/<batch_id>/stream', methods=['GET'])
def stream_batch_progress(batch_id: str):
    """Stream real-time batch progress via Server-Sent Events (SSE).

    Uses Redis pub/sub (`batch:<batch_id>:progress`) when Redis is available; otherwise
    falls back to lightweight polling of `batch_manager.get_batch_status()`.
    """

    def event_generator():
        pubsub = None
        try:
            # Prefer Redis pubsub when available
            if getattr(job_queue, 'redis_client', None):
                # Use non-blocking get_message with a short timeout instead of
                # pubsub.listen() which can raise downstream socket timeouts
                # that would bubble up after response headers are sent.
                pubsub = job_queue.redis_client.pubsub(
                    ignore_subscribe_messages=True)
                channel = f"batch:{batch_id}:progress"
                pubsub.subscribe(channel)
                try:
                    import redis as _redis
                    # Loop and poll Redis with a short timeout so we can handle
                    # transient connection/read errors without raising from the
                    # generator (which would crash the streamed response once
                    # headers have been sent).
                    while True:
                        try:
                            message = pubsub.get_message(timeout=1)
                            if not message:
                                # No message received within timeout; continue loop
                                # allowing generator to stay alive and to detect
                                # client disconnects.
                                time.sleep(0.1)
                                continue

                            if message.get('type') == 'message':
                                data = message.get('data')
                                if isinstance(data, bytes):
                                    try:
                                        text = data.decode('utf-8')
                                    except Exception:
                                        text = json.dumps({'raw': str(data)})
                                else:
                                    text = json.dumps(data)
                                yield f"data: {text}\n\n"

                        except _redis.exceptions.TimeoutError:
                            # Treat as transient; continue polling.
                            continue
                        except _redis.exceptions.ConnectionError as e:
                            logger.warning(
                                f"Redis connection error while streaming batch {batch_id}: {e}")
                            break
                        except Exception as e:
                            # Log and break to fall back to polling below. Do not
                            # re-raise, because raising here would happen after
                            # headers are sent and will surface as a framework
                            # middleware error.
                            logger.warning(
                                f"Unexpected Redis pubsub error for batch {batch_id}: {e}")
                            break
                finally:
                    try:
                        pubsub.close()
                    except Exception:
                        pass
            else:
                # Fallback polling loop
                last_payload = None
                while True:
                    try:
                        status = batch_manager.get_batch_status(batch_id)

                        # Map either per-batch or parent-aggregated structure into a
                        # consistent payload so the SSE stream consumers always get the
                        # same fields available.
                        if status and isinstance(status.get('progress'), dict):
                            p = status['progress']
                            batch_status = status.get('batch_info', {})
                            payload = {
                                'batch_id': batch_id,
                                'processed_count': p.get('processed_count', 0),
                                'successful_count': p.get('successful_count', 0),
                                'failed_count': p.get('failed_count', 0),
                                'progress_percentage': p.get('progress_percentage', 0),
                                'total_urls': p.get('total_urls', 0),
                                'status': batch_status.get('status', 'unknown')
                            }
                        else:
                            # Fallback to parent aggregated status
                            try:
                                parent_status = batch_manager.get_parent_batch_status(
                                    batch_id)
                                payload = {
                                    'batch_id': batch_id,
                                    'processed_count': parent_status.get('processed_count', 0),
                                    'successful_count': parent_status.get('successful_count', 0),
                                    'failed_count': parent_status.get('failed_count', 0),
                                    'progress_percentage': parent_status.get('progress_percentage', 0),
                                    'total_urls': parent_status.get('total_urls', 0),
                                    'status': parent_status.get('overall_status', 'unknown')
                                }
                            except Exception:
                                # Last resort: defaults
                                payload = {
                                    'batch_id': batch_id,
                                    'processed_count': 0,
                                    'successful_count': 0,
                                    'failed_count': 0,
                                    'progress_percentage': 0,
                                    'total_urls': 0,
                                    'status': 'unknown'
                                }
                        s = json.dumps(payload)
                        if s != last_payload:
                            last_payload = s
                            yield f"data: {s}\n\n"
                        time.sleep(1)
                    except GeneratorExit:
                        break
                    except Exception:
                        time.sleep(1)
                        continue
        finally:
            try:
                if pubsub:
                    pubsub.close()
            except Exception:
                pass

    return Response(stream_with_context(event_generator()), mimetype='text/event-stream')


# Error handlers
@polling_api.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found',
        'timestamp': datetime.now().isoformat()
    }), 404


@polling_api.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        'success': False,
        'error': 'Method not allowed',
        'timestamp': datetime.now().isoformat()
    }), 405


@polling_api.errorhandler(413)
def payload_too_large(error):
    return jsonify({
        'success': False,
        'error': 'File too large',
        'timestamp': datetime.now().isoformat()
    }), 413


class PollingIntervalCalculator:
    """Smart polling interval calculator based on batch status"""

    @staticmethod
    def get_recommended_interval(batch_status: str, progress_percentage: float,
                                 is_active: bool) -> int:
        """
        Get recommended polling interval in seconds

        Args:
            batch_status: Current batch status
            progress_percentage: Completion percentage (0-100)
            is_active: Whether batch is actively processing

        Returns:
            Recommended interval in seconds
        """
        if not is_active:
            # Inactive batches can be polled less frequently
            return 30

        # Active batch - adjust based on progress
        if progress_percentage < 10:
            # Early stage - poll more frequently for startup issues
            return 5
        elif progress_percentage < 50:
            # Mid stage - standard polling
            return 10
        elif progress_percentage < 90:
            # Later stage - less frequent
            return 15
        else:
            # Near completion - more frequent for completion detection
            return 5

    @staticmethod
    def get_interval_header(batch_status: str, progress_percentage: float,
                            is_active: bool) -> str:
        """Get HTTP header value for recommended polling interval"""
        interval = PollingIntervalCalculator.get_recommended_interval(
            batch_status, progress_percentage, is_active
        )
        return str(interval)


# Add interval recommendations to responses
@polling_api.after_request
def add_polling_headers(response):
    """Add recommended polling interval headers"""
    if request.endpoint and 'status' in request.endpoint:
        try:
            data = response.get_json()
            if data and data.get('success') and 'data' in data:
                batch_info = data['data'].get('batch_info', {})
                progress = data['data'].get('progress', {})

                interval = PollingIntervalCalculator.get_interval_header(
                    batch_info.get('status', ''),
                    progress.get('progress_percentage', 0),
                    batch_info.get('is_active', False)
                )

                response.headers['X-Polling-Interval'] = interval
                response.headers['X-Polling-Interval-Reason'] = 'Smart interval based on batch status'
        except:
            # If anything fails, use default interval
            response.headers['X-Polling-Interval'] = '10'

    return response
