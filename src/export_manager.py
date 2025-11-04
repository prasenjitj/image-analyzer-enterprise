"""
Enhanced export system for batch processing results with filtering and formatting options
"""
import csv
import io
import logging
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import tempfile

from .database_models import URLAnalysisResult, ProcessingBatch, db_manager
from .enterprise_config import config

logger = logging.getLogger(__name__)


class ExportManager:
    """Manages data export functionality for batch processing results"""

    def __init__(self):
        self.export_formats = ['csv', 'json', 'xlsx']
        self.max_export_size = config.max_export_rows

    def export_batch_results(self, batch_id: str, format_type: str = 'csv',
                             filters: Dict[str, Any] = None,
                             include_metadata: bool = True) -> Dict[str, Any]:
        """
        Export results for a specific batch

        Args:
            batch_id: Batch identifier
            format_type: Export format ('csv', 'json', 'xlsx')
            filters: Optional filters to apply
            include_metadata: Whether to include batch metadata

        Returns:
            Dictionary with export data and metadata
        """
        if format_type not in self.export_formats:
            raise ValueError(
                f"Unsupported format: {format_type}. Supported: {self.export_formats}")

        # Get batch information
        with db_manager.get_session() as session:
            batch = session.query(ProcessingBatch).filter_by(
                batch_id=batch_id).first()
            if not batch:
                raise ValueError(f"Batch {batch_id} not found")

            # Get results with optional filtering
            results = self._get_filtered_results(session, batch_id, filters)

            if len(results) > self.max_export_size:
                raise ValueError(
                    f"Export size ({len(results)}) exceeds maximum ({self.max_export_size})")

            # Generate export data
            export_data = self._generate_export_data(
                results, batch, format_type, include_metadata
            )

            # Create export metadata
            export_metadata = self._create_export_metadata(
                batch, len(results), format_type, filters
            )

            return {
                'data': export_data,
                'metadata': export_metadata,
                'filename': self._generate_filename(batch, format_type),
                'content_type': self._get_content_type(format_type)
            }

    def export_multiple_batches(self, batch_ids: List[str], format_type: str = 'csv',
                                include_metadata: bool = True) -> Dict[str, Any]:
        """Export results from multiple batches as a ZIP file"""
        if len(batch_ids) > 10:
            raise ValueError("Maximum 10 batches can be exported together")

        # Create temporary directory for files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for batch_id in batch_ids:
                    try:
                        # Export individual batch
                        export_result = self.export_batch_results(
                            batch_id, format_type, include_metadata=include_metadata
                        )

                        # Add to ZIP
                        filename = export_result['filename']
                        zip_file.writestr(filename, export_result['data'])

                    except Exception as e:
                        logger.error(f"Error exporting batch {batch_id}: {e}")
                        # Add error file to ZIP
                        error_filename = f"ERROR_{batch_id}.txt"
                        zip_file.writestr(
                            error_filename, f"Export failed: {str(e)}")

                # Add summary file
                summary_data = self._create_multi_batch_summary(batch_ids)
                zip_file.writestr("export_summary.txt", summary_data)

            zip_buffer.seek(0)

            return {
                'data': zip_buffer.getvalue(),
                'filename': f"multi_batch_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                'content_type': 'application/zip',
                'metadata': {
                    'batch_count': len(batch_ids),
                    'export_time': datetime.now().isoformat(),
                    'format': format_type
                }
            }

    def export_filtered_results(self, filters: Dict[str, Any], format_type: str = 'csv',
                                limit: int = None) -> Dict[str, Any]:
        """Export results with global filters across all batches"""
        with db_manager.get_session() as session:
            query = session.query(URLAnalysisResult)

            # Apply filters
            query = self._apply_global_filters(query, filters)

            # Apply limit
            if limit:
                query = query.limit(min(limit, self.max_export_size))
            else:
                # Get count to check size
                count = query.count()
                if count > self.max_export_size:
                    raise ValueError(
                        f"Result set ({count}) exceeds maximum export size ({self.max_export_size})")

            results = query.all()

            # Generate export data
            export_data = self._generate_filtered_export_data(
                results, format_type)

            return {
                'data': export_data,
                'filename': f"filtered_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format_type}",
                'content_type': self._get_content_type(format_type),
                'metadata': {
                    'record_count': len(results),
                    'filters_applied': filters,
                    'export_time': datetime.now().isoformat()
                }
            }

    def get_export_template(self, format_type: str = 'csv') -> Dict[str, Any]:
        """Get template file for data import"""
        if format_type != 'csv':
            raise ValueError("Templates only available for CSV format")

        # Create CSV template with headers
        headers = ['url', 'batch_name', 'priority']

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)

        # Write headers
        writer.writerow(headers)

        # Write example row
        writer.writerow([
            'https://example.com/image1.jpg',
            'Example Batch',
            'normal'
        ])

        return {
            'data': csv_buffer.getvalue(),
            'filename': 'import_template.csv',
            'content_type': 'text/csv',
            'metadata': {
                'description': 'Template for importing image URLs',
                'headers': headers,
                'example_included': True
            }
        }

    def _get_filtered_results(self, session, batch_id: str,
                              filters: Dict[str, Any] = None) -> List[URLAnalysisResult]:
        """Get filtered results for a batch"""
        query = session.query(URLAnalysisResult).filter_by(batch_id=batch_id)

        if filters:
            # Apply success filter
            if 'success_only' in filters and filters['success_only']:
                query = query.filter(URLAnalysisResult.success == True)
            elif 'failed_only' in filters and filters['failed_only']:
                query = query.filter(URLAnalysisResult.success == False)

            # Apply date range filter
            if 'start_date' in filters:
                query = query.filter(
                    URLAnalysisResult.created_at >= filters['start_date'])
            if 'end_date' in filters:
                query = query.filter(
                    URLAnalysisResult.created_at <= filters['end_date'])

            # Apply content filters
            if 'has_store_name' in filters and filters['has_store_name']:
                query = query.filter(URLAnalysisResult.store_name.isnot(None))
            if 'has_contact' in filters and filters['has_contact']:
                query = query.filter(
                    URLAnalysisResult.business_contact.isnot(None))

        return query.order_by(URLAnalysisResult.created_at).all()

    def _apply_global_filters(self, query, filters: Dict[str, Any]):
        """Apply filters to global query"""
        if 'batch_ids' in filters:
            query = query.filter(
                URLAnalysisResult.batch_id.in_(filters['batch_ids']))

        if 'success_only' in filters and filters['success_only']:
            query = query.filter(URLAnalysisResult.success == True)
        elif 'failed_only' in filters and filters['failed_only']:
            query = query.filter(URLAnalysisResult.success == False)

        if 'start_date' in filters:
            query = query.filter(
                URLAnalysisResult.created_at >= filters['start_date'])
        if 'end_date' in filters:
            query = query.filter(
                URLAnalysisResult.created_at <= filters['end_date'])

        if 'store_name_filter' in filters:
            query = query.filter(
                URLAnalysisResult.store_name.ilike(
                    f"%{filters['store_name_filter']}%")
            )

        return query

    def _generate_export_data(self, results: List[URLAnalysisResult],
                              batch: ProcessingBatch, format_type: str,
                              include_metadata: bool) -> str:
        """Generate export data in specified format"""
        if format_type == 'csv':
            return self._generate_csv_data(results, batch, include_metadata)
        elif format_type == 'json':
            return self._generate_json_data(results, batch, include_metadata)
        elif format_type == 'xlsx':
            return self._generate_xlsx_data(results, batch, include_metadata)
        else:
            raise ValueError(f"Unsupported format: {format_type}")

    def _generate_csv_data(self, results: List[URLAnalysisResult],
                           batch: ProcessingBatch, include_metadata: bool) -> str:
        """Generate CSV export data"""
        csv_buffer = io.StringIO()

        # Add metadata header if requested
        if include_metadata:
            csv_buffer.write(f"# Batch Export Report\n")
            csv_buffer.write(f"# Batch ID: {batch.batch_id}\n")
            csv_buffer.write(f"# Batch Name: {batch.batch_name}\n")
            csv_buffer.write(f"# Export Date: {datetime.now().isoformat()}\n")
            csv_buffer.write(f"# Total Records: {len(results)}\n")
            csv_buffer.write(f"# Batch Status: {batch.status.value}\n")
            csv_buffer.write(f"# \n")

        # CSV headers
        headers = [
            'url', 'success', 'store_image', 'text_content', 'store_name',
            'business_contact', 'image_description', 'error_message',
            'processing_time_seconds', 'created_at', 'batch_id'
        ]

        writer = csv.writer(csv_buffer)
        writer.writerow(headers)

        # Write data rows
        for result in results:
            writer.writerow([
                result.url,
                'Yes' if result.success else 'No',
                'Yes' if result.store_image else 'No',
                result.text_content or '',
                result.store_name or '',
                result.business_contact or '',
                result.image_description or '',
                result.error_message or '',
                result.processing_time_seconds or 0,
                result.created_at.isoformat() if result.created_at else '',
                result.batch_id
            ])

        return csv_buffer.getvalue()

    def _generate_json_data(self, results: List[URLAnalysisResult],
                            batch: ProcessingBatch, include_metadata: bool) -> str:
        """Generate JSON export data"""
        import json

        data = {
            'results': [result.to_dict() for result in results]
        }

        if include_metadata:
            data['metadata'] = {
                'batch_id': str(batch.batch_id),
                'batch_name': batch.batch_name,
                'export_date': datetime.now().isoformat(),
                'total_records': len(results),
                'batch_status': batch.status.value,
                'batch_created': batch.created_at.isoformat() if batch.created_at else None,
                'batch_started': batch.started_at.isoformat() if batch.started_at else None
            }

        return json.dumps(data, indent=2, ensure_ascii=False)

    def _generate_xlsx_data(self, results: List[URLAnalysisResult],
                            batch: ProcessingBatch, include_metadata: bool) -> bytes:
        """Generate Excel export data"""
        try:
            import pandas as pd
            import openpyxl
        except ImportError:
            raise ValueError("pandas and openpyxl required for Excel export")

        # Convert results to DataFrame
        data = []
        for result in results:
            data.append({
                'URL': result.url,
                'Success': 'Yes' if result.success else 'No',
                'Store Image': 'Yes' if result.store_image else 'No',
                'Text Content': result.text_content or '',
                'Store Name': result.store_name or '',
                'Business Contact': result.business_contact or '',
                'Image Description': result.image_description or '',
                'Error Message': result.error_message or '',
                'Processing Time (seconds)': result.processing_time_seconds or 0,
                'Created At': result.created_at,
                'Batch ID': result.batch_id
            })

        df = pd.DataFrame(data)

        # Create Excel buffer
        excel_buffer = io.BytesIO()

        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            # Write main data
            df.to_excel(writer, sheet_name='Results', index=False)

            # Add metadata sheet if requested
            if include_metadata:
                metadata_df = pd.DataFrame([
                    ['Batch ID', str(batch.batch_id)],
                    ['Batch Name', batch.batch_name],
                    ['Export Date', datetime.now().isoformat()],
                    ['Total Records', len(results)],
                    ['Batch Status', batch.status.value],
                    ['Batch Created', batch.created_at.isoformat()
                     if batch.created_at else ''],
                    ['Batch Started', batch.started_at.isoformat()
                     if batch.started_at else '']
                ], columns=['Property', 'Value'])

                metadata_df.to_excel(
                    writer, sheet_name='Metadata', index=False)

        excel_buffer.seek(0)
        return excel_buffer.getvalue()

    def _generate_filtered_export_data(self, results: List[URLAnalysisResult],
                                       format_type: str) -> Union[str, bytes]:
        """Generate export data for filtered results"""
        if format_type == 'csv':
            csv_buffer = io.StringIO()

            headers = [
                'url', 'success', 'store_image', 'text_content', 'store_name',
                'business_contact', 'image_description', 'error_message',
                'processing_time_seconds', 'created_at', 'batch_id'
            ]

            writer = csv.writer(csv_buffer)
            writer.writerow(headers)

            for result in results:
                writer.writerow([
                    result.url,
                    'Yes' if result.success else 'No',
                    'Yes' if result.store_image else 'No',
                    result.text_content or '',
                    result.store_name or '',
                    result.business_contact or '',
                    result.image_description or '',
                    result.error_message or '',
                    result.processing_time_seconds or 0,
                    result.created_at.isoformat() if result.created_at else '',
                    result.batch_id
                ])

            return csv_buffer.getvalue()

        elif format_type == 'json':
            import json
            data = {
                'results': [result.to_dict() for result in results],
                'export_metadata': {
                    'export_date': datetime.now().isoformat(),
                    'total_records': len(results)
                }
            }
            return json.dumps(data, indent=2, ensure_ascii=False)

        else:
            raise ValueError(
                f"Format {format_type} not supported for filtered exports")

    def _create_export_metadata(self, batch: ProcessingBatch, result_count: int,
                                format_type: str, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create export metadata"""
        return {
            'batch_id': str(batch.batch_id),
            'batch_name': batch.batch_name,
            'export_date': datetime.now().isoformat(),
            'format': format_type,
            'record_count': result_count,
            'total_batch_urls': batch.total_urls,
            'batch_status': batch.status.value,
            'filters_applied': filters or {},
            'export_version': '1.0'
        }

    def _create_multi_batch_summary(self, batch_ids: List[str]) -> str:
        """Create summary for multi-batch export"""
        summary = f"Multi-Batch Export Summary\n"
        summary += f"Export Date: {datetime.now().isoformat()}\n"
        summary += f"Number of Batches: {len(batch_ids)}\n"
        summary += f"Batch IDs:\n"

        for batch_id in batch_ids:
            summary += f"  - {batch_id}\n"

        summary += f"\nFiles included:\n"
        for batch_id in batch_ids:
            summary += f"  - {batch_id}_results.csv\n"

        return summary

    def _generate_filename(self, batch: ProcessingBatch, format_type: str) -> str:
        """Generate filename for export"""
        safe_name = "".join(
            c for c in batch.batch_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        return f"{safe_name}_{timestamp}.{format_type}"

    def _get_content_type(self, format_type: str) -> str:
        """Get content type for format"""
        content_types = {
            'csv': 'text/csv',
            'json': 'application/json',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }
        return content_types.get(format_type, 'application/octet-stream')

    def get_export_statistics(self) -> Dict[str, Any]:
        """Get export usage statistics"""
        with db_manager.get_session() as session:
            total_results = session.query(URLAnalysisResult).count()
            successful_results = session.query(
                URLAnalysisResult).filter_by(success=True).count()

            # Get batch statistics
            from sqlalchemy import func
            batch_stats = session.query(
                func.count(ProcessingBatch.batch_id).label('total_batches'),
                func.sum(ProcessingBatch.total_urls).label('total_urls'),
                func.sum(ProcessingBatch.successful_count).label(
                    'total_successful')
            ).first()

            return {
                'total_results_available': total_results,
                'successful_results_available': successful_results,
                'total_batches': batch_stats.total_batches or 0,
                'total_urls_processed': batch_stats.total_urls or 0,
                'total_successful_urls': batch_stats.total_successful or 0,
                'max_export_size': self.max_export_size,
                'supported_formats': self.export_formats
            }


# Global export manager instance
export_manager = ExportManager()
