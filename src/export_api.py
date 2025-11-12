"""
Export API endpoints for enterprise batch processing system

Provides comprehensive export functionality with filtering, multiple formats,
and batch operations.
"""
from flask import Blueprint, request, jsonify, send_file, Response
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import tempfile
import os
from io import BytesIO, StringIO

from .export_manager import export_manager
from .database_models import ProcessingBatch, db_manager

logger = logging.getLogger(__name__)

# Create Blueprint for export API
export_api = Blueprint('export_api', __name__, url_prefix='/api/v1/export')


@export_api.route('/batch/<batch_id>', methods=['GET'])
def export_batch_results(batch_id: str):
    """Export results for a specific batch with filtering options"""
    try:
        # Get query parameters
        format_type = request.args.get('format', 'csv')
        include_metadata = request.args.get(
            'metadata', 'true').lower() == 'true'

        # Parse filters
        filters = {}

        # Success/failure filters
        if request.args.get('failed_only') == 'true':
            filters['failed_only'] = True

        # Date range filters
        if request.args.get('start_date'):
            try:
                filters['start_date'] = datetime.fromisoformat(
                    request.args.get('start_date'))
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': 'Invalid start_date format. Use ISO format: YYYY-MM-DDTHH:MM:SS'
                }), 400

        if request.args.get('end_date'):
            try:
                filters['end_date'] = datetime.fromisoformat(
                    request.args.get('end_date'))
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': 'Invalid end_date format. Use ISO format: YYYY-MM-DDTHH:MM:SS'
                }), 400

        # Content filters
        if request.args.get('has_store_name') == 'true':
            filters['has_store_name'] = True
        if request.args.get('has_contact') == 'true':
            filters['has_contact'] = True

        # Generate export
        export_result = export_manager.export_batch_results(
            batch_id=batch_id,
            format_type=format_type,
            filters=filters,
            include_metadata=include_metadata
        )

        # Create response based on format
        if format_type == 'xlsx':
            # Binary response for Excel
            return Response(
                export_result['data'],
                mimetype=export_result['content_type'],
                headers={
                    'Content-Disposition': f'attachment; filename="{export_result["filename"]}"',
                    'Content-Length': str(len(export_result['data']))
                }
            )
        else:
            # Text response for CSV/JSON
            return Response(
                export_result['data'],
                mimetype=export_result['content_type'],
                headers={
                    'Content-Disposition': f'attachment; filename="{export_result["filename"]}"',
                    'Content-Length': str(len(export_result['data'].encode('utf-8')))
                }
            )

    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 404

    except Exception as e:
        logger.error(f"Error exporting batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/batches/multiple', methods=['POST'])
def export_multiple_batches():
    """Export multiple batches as a ZIP file"""
    try:
        data = request.get_json()

        if not data or 'batch_ids' not in data:
            return jsonify({
                'success': False,
                'error': 'batch_ids array is required'
            }), 400

        batch_ids = data['batch_ids']
        format_type = data.get('format', 'csv')
        include_metadata = data.get('metadata', True)

        if not isinstance(batch_ids, list) or len(batch_ids) == 0:
            return jsonify({
                'success': False,
                'error': 'batch_ids must be a non-empty array'
            }), 400

        if len(batch_ids) > 10:
            return jsonify({
                'success': False,
                'error': 'Maximum 10 batches can be exported together'
            }), 400

        # Generate multi-batch export
        export_result = export_manager.export_multiple_batches(
            batch_ids=batch_ids,
            format_type=format_type,
            include_metadata=include_metadata
        )

        return Response(
            export_result['data'],
            mimetype=export_result['content_type'],
            headers={
                'Content-Disposition': f'attachment; filename="{export_result["filename"]}"',
                'Content-Length': str(len(export_result['data']))
            }
        )

    except Exception as e:
        logger.error(f"Error exporting multiple batches: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/filtered', methods=['POST'])
def export_filtered_results():
    """Export results with global filters across all batches"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'error': 'Request body is required'
            }), 400

        filters = data.get('filters', {})
        format_type = data.get('format', 'csv')
        limit = data.get('limit')

        # Validate filters
        if 'batch_ids' in filters:
            if not isinstance(filters['batch_ids'], list):
                return jsonify({
                    'success': False,
                    'error': 'batch_ids must be an array'
                }), 400

        # Parse date filters
        for date_field in ['start_date', 'end_date']:
            if date_field in filters:
                try:
                    filters[date_field] = datetime.fromisoformat(
                        filters[date_field])
                except ValueError:
                    return jsonify({
                        'success': False,
                        'error': f'Invalid {date_field} format. Use ISO format: YYYY-MM-DDTHH:MM:SS'
                    }), 400

        # Generate filtered export
        export_result = export_manager.export_filtered_results(
            filters=filters,
            format_type=format_type,
            limit=limit
        )

        if format_type == 'xlsx':
            # Binary response for Excel
            return Response(
                export_result['data'],
                mimetype=export_result['content_type'],
                headers={
                    'Content-Disposition': f'attachment; filename="{export_result["filename"]}"',
                    'Content-Length': str(len(export_result['data']))
                }
            )
        else:
            # Text response for CSV/JSON
            return Response(
                export_result['data'],
                mimetype=export_result['content_type'],
                headers={
                    'Content-Disposition': f'attachment; filename="{export_result["filename"]}"',
                    'Content-Length': str(len(export_result['data'].encode('utf-8')))
                }
            )

    except Exception as e:
        logger.error(f"Error exporting filtered results: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/template', methods=['GET'])
def download_template():
    """Download CSV import template"""
    try:
        format_type = request.args.get('format', 'csv')

        if format_type != 'csv':
            return jsonify({
                'success': False,
                'error': 'Templates only available for CSV format'
            }), 400

        template = export_manager.get_export_template(format_type)

        return Response(
            template['data'],
            mimetype=template['content_type'],
            headers={
                'Content-Disposition': f'attachment; filename="{template["filename"]}"',
                'Content-Length': str(len(template['data'].encode('utf-8')))
            }
        )

    except Exception as e:
        logger.error(f"Error generating template: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/statistics', methods=['GET'])
def get_export_statistics():
    """Get export usage statistics"""
    try:
        stats = export_manager.get_export_statistics()

        return jsonify({
            'success': True,
            'data': stats,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting export statistics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/batch/<batch_id>/preview', methods=['GET'])
def preview_batch_export(batch_id: str):
    """Preview batch export data (first 100 records)"""
    try:
        # Get query parameters
        format_type = request.args.get('format', 'csv')

        # Parse filters (same as export)
        filters = {}
        # Success/failure filters
        if request.args.get('failed_only') == 'true':
            filters['failed_only'] = True

        # Limit preview to 100 records
        from .database_models import URLAnalysisResult

        with db_manager.get_session() as session:
            query = session.query(
                URLAnalysisResult).filter_by(batch_id=batch_id)

            # Apply filters
            if filters.get('failed_only'):
                query = query.filter(URLAnalysisResult.success == False)

            results = query.limit(100).all()

            if not results:
                return jsonify({
                    'success': False,
                    'error': f'No results found for batch {batch_id}'
                }), 404

            # Convert to preview format
            preview_data = []
            for result in results:
                preview_data.append({
                    'url': result.url,
                    'success': result.success,
                    'store_image': result.store_image,
                    'text_content': result.text_content,
                    'store_name': result.store_name,
                    'store_front_match_score': getattr(result, 'store_front_match_score', None),
                    'store_front_match': getattr(result, 'store_front_match', None),
                    'business_contact': result.business_contact,
                    'image_description': result.image_description,
                    'error_message': result.error_message,
                    'created_at': result.created_at.isoformat() if result.created_at else None
                })

            return jsonify({
                'success': True,
                'data': {
                    'preview_records': preview_data,
                    'total_records_shown': len(preview_data),
                    'is_preview': True,
                    'filters_applied': filters
                },
                'timestamp': datetime.now().isoformat()
            })

    except Exception as e:
        logger.error(f"Error previewing batch {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/formats', methods=['GET'])
def get_supported_formats():
    """Get list of supported export formats"""
    try:
        formats = {
            'csv': {
                'name': 'Comma Separated Values',
                'description': 'Standard CSV format for spreadsheet applications',
                'supports_filtering': True,
                'supports_metadata': True,
                'file_extension': '.csv',
                'mime_type': 'text/csv'
            },
            'json': {
                'name': 'JavaScript Object Notation',
                'description': 'JSON format for API integrations and applications',
                'supports_filtering': True,
                'supports_metadata': True,
                'file_extension': '.json',
                'mime_type': 'application/json'
            },
            'xlsx': {
                'name': 'Microsoft Excel',
                'description': 'Excel format with multiple sheets and formatting',
                'supports_filtering': True,
                'supports_metadata': True,
                'file_extension': '.xlsx',
                'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            }
        }

        return jsonify({
            'success': True,
            'data': {
                'supported_formats': formats,
                'default_format': 'csv'
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting supported formats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@export_api.route('/batch/<batch_id>/summary', methods=['GET'])
def get_batch_export_summary(batch_id: str):
    """Get summary information for batch export"""
    try:
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()

            if not batch:
                return jsonify({
                    'success': False,
                    'error': f'Batch {batch_id} not found'
                }), 404

            # Get result counts
            from .database_models import URLAnalysisResult

            total_results = session.query(
                URLAnalysisResult).filter_by(batch_id=batch_id).count()
            successful_results = session.query(URLAnalysisResult).filter_by(
                batch_id=batch_id, success=True
            ).count()
            failed_results = total_results - successful_results

            # Calculate estimated export sizes (rough estimates)
            csv_size_mb = (total_results * 200) / \
                (1024 * 1024)  # ~200 bytes per row
            json_size_mb = (total_results * 400) / \
                (1024 * 1024)  # ~400 bytes per row
            xlsx_size_mb = (total_results * 150) / \
                (1024 * 1024)  # ~150 bytes per row

            summary = {
                'batch_info': {
                    'batch_id': batch_id,
                    'batch_name': batch.batch_name,
                    'status': batch.status.value,
                    'created_at': batch.created_at.isoformat() if batch.created_at else None
                },
                'export_summary': {
                    'total_results': total_results,
                    'successful_results': successful_results,
                    'failed_results': failed_results,
                    'success_rate': (successful_results / max(total_results, 1)) * 100
                },
                'estimated_sizes_mb': {
                    'csv': round(csv_size_mb, 2),
                    'json': round(json_size_mb, 2),
                    'xlsx': round(xlsx_size_mb, 2)
                },
                'available_filters': {
                    'failed_only': f'{failed_results} records',
                    'has_store_name': 'Records with store names',
                    'has_contact': 'Records with business contacts'
                }
            }

            return jsonify({
                'success': True,
                'data': summary,
                'timestamp': datetime.now().isoformat()
            })

    except Exception as e:
        logger.error(f"Error getting batch export summary for {batch_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Error handlers for export API
@export_api.errorhandler(404)
def export_not_found(error):
    return jsonify({
        'success': False,
        'error': 'Export resource not found',
        'timestamp': datetime.now().isoformat()
    }), 404


@export_api.errorhandler(413)
def export_payload_too_large(error):
    return jsonify({
        'success': False,
        'error': 'Export request too large',
        'timestamp': datetime.now().isoformat()
    }), 413


@export_api.errorhandler(500)
def export_server_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error during export',
        'timestamp': datetime.now().isoformat()
    }), 500


# Add response headers for export API
@export_api.after_request
def add_export_headers(response):
    """Add helpful headers to export responses"""

    # Add CORS headers for API access
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

    # Add caching headers for static exports
    if request.endpoint and 'template' in request.endpoint:
        # Cache templates for 1 hour
        response.headers['Cache-Control'] = 'public, max-age=3600'

    # Add export API version
    response.headers['X-Export-API-Version'] = '1.0'

    return response
