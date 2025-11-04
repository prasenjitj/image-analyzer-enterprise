# Image Analyzer Enterprise API Documentation

## Overview

The Image Analyzer Enterprise API provides comprehensive batch processing capabilities for analyzing large volumes of images and URLs. The system supports PostgreSQL, Redis, background processing, and offers robust monitoring and export functionality.

**Base URL**: `http://localhost:5001` (default)  
**API Version**: v1  
**Content-Type**: `application/json` (unless specified otherwise)

## Table of Contents

1. [Authentication](#authentication)
2. [Batch Management API](#batch-management-api)
3. [Polling API](#polling-api)
4. [Export API](#export-api)
5. [System Management](#system-management)
6. [Web Interface Endpoints](#web-interface-endpoints)
7. [Data Models](#data-models)
8. [Error Handling](#error-handling)
9. [Rate Limits](#rate-limits)
10. [Examples](#examples)

## Authentication

Currently, the API does not require authentication for local development. For production deployment, implement authentication middleware as needed.

**API Keys**: The system uses Google Vision API keys internally for image processing. Configure these via environment variables.

## Batch Management API

### Create Batch
Create a new batch for processing from CSV upload.

**Endpoint**: `POST /api/v1/batches`  
**Content-Type**: `multipart/form-data`

**Parameters**:
- `file` (required): CSV file containing URLs to process
- `batch_name` (optional): Custom name for the batch
- `auto_start` (optional): Whether to automatically start processing (default: `true`)

**Response**:
```json
{
  "success": true,
  "data": {
    "batch_id": "123e4567-e89b-12d3-a456-426614174000",
    "batch_info": {
      "batch_name": "My Image Analysis Batch",
      "total_urls": 1500,
      "total_chunks": 2,
      "status": "QUEUED",
      "auto_started": true
    }
  },
  "message": "Batch created and processing started",
  "timestamp": "2025-11-02T10:30:00Z"
}
```

### List Batches
Get all batches with pagination and filtering.

**Endpoint**: `GET /api/v1/batches`

**Query Parameters**:
- `limit` (optional): Number of batches to return (max 100, default 50)
- `status` (optional): Filter by status (`pending`, `queued`, `processing`, `completed`, `failed`, `cancelled`)
- `page` (optional): Page number for pagination
- `per_page` (optional): Items per page
- `include_soft_deleted` (optional): Include soft-deleted batches (default: `false`)

**Response**:
```json
{
  "success": true,
  "data": {
    "batches": [
      {
        "batch_id": "123e4567-e89b-12d3-a456-426614174000",
        "batch_name": "My Image Analysis Batch",
        "status": "processing",
        "total_urls": 1500,
        "processed_count": 750,
        "progress_percentage": 50.0,
        "created_at": "2025-11-02T10:30:00Z",
        "started_at": "2025-11-02T10:30:15Z"
      }
    ],
    "count": 1
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Get Batch Details
Get comprehensive details for a specific batch.

**Endpoint**: `GET /api/v1/batch/{batch_id}`

**Response**:
```json
{
  "success": true,
  "data": {
    "batch_info": {
      "batch_id": "123e4567-e89b-12d3-a456-426614174000",
      "batch_name": "My Image Analysis Batch",
      "status": "processing",
      "total_urls": 1500,
      "chunk_size": 2000,  // Updated default optimized chunk size
      "total_chunks": 2,
      "is_active": true,
      "created_at": "2025-11-02T10:30:00Z",
      "started_at": "2025-11-02T10:30:15Z"
    },
    "progress": {
      "processed_count": 750,
      "successful_count": 720,
      "failed_count": 30,
      "progress_percentage": 50.0,
      "current_chunk": 1,
      "total_chunks": 2
    },
    "timing": {
      "estimated_completion": "2025-11-02T11:15:00Z",
      "elapsed_time_minutes": 15
    },
    "performance": {
      "processing_rate_per_minute": 50.0,
      "success_rate": 96.0,
      "average_time_per_url": 1.2
    }
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

## Polling API

### Get Batch Status
Get detailed status for polling and monitoring.

**Endpoint**: `GET /api/v1/batches/{batch_id}/status`

**Headers**:
- `X-Polling-Interval`: Recommended polling interval in seconds

**Response**: Same as batch details above, with additional polling headers.

### Get Batch Progress
Get lightweight progress information optimized for frequent polling.

**Endpoint**: `GET /api/v1/batches/{batch_id}/progress`

**Response**:
```json
{
  "success": true,
  "data": {
    "batch_id": "123e4567-e89b-12d3-a456-426614174000",
    "status": "processing",
    "progress_percentage": 50.0,
    "processed_count": 750,
    "total_urls": 1500,
    "successful_count": 720,
    "failed_count": 30,
    "current_chunk": 1,
    "total_chunks": 2,
    "estimated_completion": "2025-11-02T11:15:00Z",
    "processing_rate_per_minute": 50.0,
    "is_active": true
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Batch Control Operations

#### Start Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/start`

#### Pause Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/pause`

#### Resume Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/resume`

#### Cancel Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/cancel`

#### Force Start Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/force-start`

**Request Body**:
```json
{
  "skip_validation": false
}
```

All control operations return:
```json
{
  "success": true,
  "data": {
    "batch_id": "123e4567-e89b-12d3-a456-426614174000",
    "started": true
  },
  "message": "Batch processing started",
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Advanced Batch Operations

#### Clone Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/clone`

**Request Body**:
```json
{
  "new_name": "Cloned Batch Name",
  "copy_results": false
}
```

#### Soft Delete Batch
**Endpoint**: `POST /api/v1/batches/{batch_id}/soft-delete`

**Request Body**:
```json
{
  "retention_days": 30
}
```

#### Delete Batch
**Endpoint**: `DELETE /api/v1/batches/{batch_id}`

**Query Parameters**:
- `force` (optional): Force delete even if active (default: `false`)

### Batch Analytics

#### Get Batch Health Score
**Endpoint**: `GET /api/v1/batches/{batch_id}/health`

**Response**:
```json
{
  "success": true,
  "data": {
    "health_score": 95.5,
    "factors": {
      "success_rate": 96.0,
      "processing_speed": 95.0,
      "error_patterns": 100.0
    },
    "recommendations": [
      "Batch is performing well",
      "Monitor for rate limiting"
    ]
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

#### Analyze Batch Errors
**Endpoint**: `GET /api/v1/batches/{batch_id}/analyze`

**Response**:
```json
{
  "success": true,
  "data": {
    "total_errors": 30,
    "error_categories": {
      "network_errors": 15,
      "invalid_urls": 10,
      "processing_errors": 5
    },
    "top_errors": [
      {
        "error_type": "connection_timeout",
        "count": 12,
        "percentage": 40.0
      }
    ],
    "recommendations": [
      "Check network connectivity",
      "Validate URL format"
    ]
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Get Batch Chunks
**Endpoint**: `GET /api/v1/batches/{batch_id}/chunks`

**Response**:
```json
{
  "success": true,
  "data": {
    "batch_id": "123e4567-e89b-12d3-a456-426614174000",
    "chunks": [
      {
        "chunk_id": "456e7890-e89b-12d3-a456-426614174001",
        "chunk_number": 1,
        "status": "completed",
        "url_count": 1000,
        "processed_count": 1000,
        "successful_count": 950,
        "failed_count": 50,
        "progress_percentage": 100.0,
        "started_at": "2025-11-02T10:30:15Z",
        "completed_at": "2025-11-02T10:45:00Z",
        "processing_time_seconds": 885.5
      }
    ],
    "total_chunks": 2
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

## Export API

### Export Batch Results
Export results for a specific batch with filtering options.

**Endpoint**: `GET /api/v1/export/batch/{batch_id}`

**Query Parameters**:
- `format` (optional): Export format (`csv`, `json`, `xlsx`) (default: `csv`)
- `metadata` (optional): Include metadata fields (default: `true`)
- `success_only` (optional): Export only successful results (default: `false`)
- `failed_only` (optional): Export only failed results (default: `false`)
- `start_date` (optional): Filter results from date (ISO format)
- `end_date` (optional): Filter results to date (ISO format)
- `has_store_name` (optional): Include only results with store names
- `has_contact` (optional): Include only results with business contacts

**Response**: File download with appropriate Content-Type header.

### Export Multiple Batches
**Endpoint**: `POST /api/v1/export/batches/multiple`

**Request Body**:
```json
{
  "batch_ids": [
    "123e4567-e89b-12d3-a456-426614174000",
    "789e0123-e89b-12d3-a456-426614174001"
  ],
  "format": "csv",
  "metadata": true
}
```

**Response**: ZIP file containing individual batch exports.

### Export with Global Filters
**Endpoint**: `POST /api/v1/export/filtered`

**Request Body**:
```json
{
  "filters": {
    "batch_ids": ["batch1", "batch2"],
    "start_date": "2025-11-01T00:00:00Z",
    "end_date": "2025-11-02T23:59:59Z",
    "success_only": true
  },
  "format": "xlsx",
  "limit": 10000
}
```

### Download Import Template
**Endpoint**: `GET /api/v1/export/template`

**Query Parameters**:
- `format` (optional): Template format (default: `csv`)

**Response**: CSV template file for batch uploads.

### Export Statistics
**Endpoint**: `GET /api/v1/export/statistics`

**Response**:
```json
{
  "success": true,
  "data": {
    "total_exports": 150,
    "exports_today": 12,
    "popular_formats": {
      "csv": 60,
      "xlsx": 30,
      "json": 10
    },
    "average_export_size_mb": 2.5
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Preview Batch Export
**Endpoint**: `GET /api/v1/export/batch/{batch_id}/preview`

**Query Parameters**: Same as export batch results

**Response**:
```json
{
  "success": true,
  "data": {
    "preview_records": [
      {
        "url": "https://example.com/image1.jpg",
        "success": true,
        "store_image": true,
        "text_content": "Store front image",
        "store_name": "Example Store",
        "business_contact": "contact@example.com",
        "image_description": "Modern storefront with glass windows",
        "error_message": null,
        "created_at": "2025-11-02T10:30:00Z"
      }
    ],
    "total_records_shown": 100,
    "is_preview": true,
    "filters_applied": {}
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Get Supported Export Formats
**Endpoint**: `GET /api/v1/export/formats`

**Response**:
```json
{
  "success": true,
  "data": {
    "supported_formats": {
      "csv": {
        "name": "Comma Separated Values",
        "description": "Standard CSV format for spreadsheet applications",
        "supports_filtering": true,
        "supports_metadata": true,
        "file_extension": ".csv",
        "mime_type": "text/csv"
      },
      "json": {
        "name": "JavaScript Object Notation",
        "description": "JSON format for API integrations",
        "supports_filtering": true,
        "supports_metadata": true,
        "file_extension": ".json",
        "mime_type": "application/json"
      },
      "xlsx": {
        "name": "Microsoft Excel",
        "description": "Excel format with multiple sheets",
        "supports_filtering": true,
        "supports_metadata": true,
        "file_extension": ".xlsx",
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      }
    },
    "default_format": "csv"
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Get Batch Export Summary
**Endpoint**: `GET /api/v1/export/batch/{batch_id}/summary`

**Response**:
```json
{
  "success": true,
  "data": {
    "batch_info": {
      "batch_id": "123e4567-e89b-12d3-a456-426614174000",
      "batch_name": "My Image Analysis Batch",
      "status": "completed",
      "created_at": "2025-11-02T10:30:00Z"
    },
    "export_summary": {
      "total_results": 1500,
      "successful_results": 1440,
      "failed_results": 60,
      "success_rate": 96.0
    },
    "estimated_sizes_mb": {
      "csv": 2.86,
      "json": 5.72,
      "xlsx": 2.15
    },
    "available_filters": {
      "success_only": "1440 records",
      "failed_only": "60 records",
      "has_store_name": "Records with store names",
      "has_contact": "Records with business contacts"
    }
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

## System Management

### System Statistics
**Endpoint**: `GET /api/v1/system/stats`

**Response**:
```json
{
  "success": true,
  "data": {
    "total_batches": 50,
    "active_batches": 3,
    "completed_batches": 45,
    "total_urls_processed": 125000,
    "overall_success_rate": 94.5,
    "queue_stats": {
      "pending": 5,
      "processing": 2,
      "completed": 1240,
      "failed": 8
    }
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Health Check
**Endpoint**: `GET /api/v1/health`

**Response**:
```json
{
  "success": true,
  "data": {
    "status": "healthy",
    "database": "connected",
    "redis": "connected",
    "config": {
      "chunk_size": 2000,  // Updated optimized chunk size
      "max_concurrent_batches": 20,  // Updated for higher throughput
      "max_concurrent_workers": 100,  // Updated worker count
      "api_keys_count": 3
    }
  },
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### Admin Queue Management

#### Get Queue Status
**Endpoint**: `GET /admin/queue/status`

**Response**:
```json
{
  "success": true,
  "data": {
    "queue_stats": {
      "pending": 5,
      "processing": 2,
      "retrying": 1,
      "completed": 1240,
      "failed": 8
    },
    "total_stuck": 0,
    "stuck_jobs": [],
    "recommendations": ["Queue is operating normally"]
  }
}
```

#### Clean Up Queue
**Endpoint**: `POST /admin/queue/cleanup`

**Request Body**:
```json
{
  "job_types": ["process_chunk", "chunk_processing"],
  "max_age_hours": 24,
  "clean_database": true
}
```

#### Reset Stuck Batch
**Endpoint**: `POST /admin/batch/{batch_id}/reset`

**Request Body**:
```json
{
  "force": false
}
```

## Web Interface Endpoints

### Dashboard
**Endpoint**: `GET /`  
Main enterprise dashboard with batch overview.

### Batch Detail Page
**Endpoint**: `GET /batch/{batch_id}`  
Detailed view of specific batch.

### Upload CSV
**Endpoint**: `POST /upload`  
Web form for CSV upload (same as API but returns HTML redirect).

### System Status Page
**Endpoint**: `GET /system/status`  
System monitoring dashboard.

### Admin Dashboard
**Endpoint**: `GET /admin`  
Administrative interface for system management.

### Export Download
**Endpoint**: `GET /export/batch/{batch_id}`  
Direct download of batch results (web interface).

### Template Download
**Endpoint**: `GET /export/template`  
Download CSV import template.

## Data Models

### ProcessingBatch
```json
{
  "batch_id": "uuid",
  "batch_name": "string",
  "total_urls": "integer",
  "chunk_size": "integer",
  "total_chunks": "integer",
  "processed_count": "integer",
  "successful_count": "integer",
  "failed_count": "integer",
  "current_chunk": "integer",
  "status": "enum: pending|queued|processing|paused|completed|failed|cancelled",
  "created_at": "datetime",
  "started_at": "datetime",
  "completed_at": "datetime",
  "estimated_completion": "datetime",
  "processing_rate": "float",
  "success_rate": "float",
  "original_filename": "string",
  "error_message": "string",
  "retry_count": "integer"
}
```

### ProcessingChunk
```json
{
  "chunk_id": "uuid",
  "batch_id": "uuid",
  "chunk_number": "integer",
  "urls": "array",
  "url_count": "integer",
  "processed_count": "integer",
  "successful_count": "integer",
  "failed_count": "integer",
  "status": "enum: pending|processing|completed|failed|retrying",
  "queued_at": "datetime",
  "started_at": "datetime",
  "completed_at": "datetime",
  "processing_time_seconds": "float",
  "error_message": "string",
  "worker_id": "string"
}
```

### URLAnalysisResult
```json
{
  "result_id": "uuid",
  "url": "string",
  "batch_id": "uuid",
  "chunk_id": "uuid",
  "analysis_result": "object",
  "store_image": "boolean",
  "text_content": "string",
  "store_name": "string",
  "business_contact": "string",
  "image_description": "string",
  "success": "boolean",
  "error_message": "string",
  "processing_time_seconds": "float",
  "api_key_used": "string",
  "created_at": "datetime",
  "cache_hit": "boolean",
  "gemini_model_used": "string"
}
```

## Error Handling

### Standard Error Response
```json
{
  "success": false,
  "error": "Error message description",
  "timestamp": "2025-11-02T10:45:00Z"
}
```

### HTTP Status Codes
- `200 OK`: Successful request
- `201 Created`: Resource created successfully
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `413 Payload Too Large`: File or request too large
- `500 Internal Server Error`: Server error

### Common Error Types
- **ValidationError**: Invalid input parameters
- **BatchNotFound**: Batch ID does not exist
- **BatchStateError**: Operation not allowed in current batch state
- **ProcessingError**: Error during batch processing
- **ExportError**: Error during export generation
- **SystemError**: System connectivity or configuration issues

## Rate Limits (Updated for Performance)

### API Rate Limits (Optimized)
- Default: 1000 requests per hour per IP
- Batch operations: 20 concurrent batches maximum (increased from 10)
- Upload size: 200MB maximum file size (increased from 100MB)
- Export size: 1M records maximum per export
- Chunk size: 2000 URLs per chunk (optimized from 1000)

### Google Vision API Limits (Enhanced)
- Base: 55 requests per minute per API key
- With multiple keys: Up to 200+ requests per minute total
- Automatic rate limiting and retry logic
- Dynamic rate adjustment based on API response patterns
- Support for 6+ API keys for maximum throughput

### Performance Configuration
Current optimized defaults:
- `MAX_CONCURRENT_WORKERS`: 100
- `MAX_CONCURRENT_BATCHES`: 20  
- `MAX_CONCURRENT_REQUESTS`: 25
- `CHUNK_SIZE`: 2000
- `DATABASE_POOL_SIZE`: 200
- `REDIS_MAX_CONNECTIONS`: 1000

> **Note**: For comprehensive performance tuning and optimization strategies, see [PERFORMANCE_OPTIMIZATION_GUIDE.md](../PERFORMANCE_OPTIMIZATION_GUIDE.md).

## Examples

### Complete Batch Processing Workflow

#### 1. Create and Start Batch
```bash
curl -X POST http://localhost:5001/api/v1/batches \
  -F "file=@urls.csv" \
  -F "batch_name=My Test Batch" \
  -F "auto_start=true"
```

#### 2. Monitor Progress
```bash
curl http://localhost:5001/api/v1/batches/{batch_id}/progress
```

#### 3. Export Results
```bash
curl "http://localhost:5001/api/v1/export/batch/{batch_id}?format=csv&success_only=true" \
  -o results.csv
```

### Polling Implementation
```javascript
async function pollBatchStatus(batchId) {
  while (true) {
    const response = await fetch(`/api/v1/batches/${batchId}/progress`);
    const data = await response.json();
    
    if (data.success) {
      console.log(`Progress: ${data.data.progress_percentage}%`);
      
      if (!data.data.is_active) {
        console.log('Batch completed');
        break;
      }
      
      // Use recommended polling interval from headers
      const interval = parseInt(response.headers.get('X-Polling-Interval') || '10');
      await new Promise(resolve => setTimeout(resolve, interval * 1000));
    }
  }
}
```

### CSV Upload Format
```csv
url
https://example.com/image1.jpg
https://example.com/image2.png
https://example.com/image3.gif
```

### Batch Control Example
```bash
# Pause batch
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/pause

# Resume batch  
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/resume

# Cancel batch
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/cancel
```

### Error Analysis
```bash
curl http://localhost:5001/api/v1/batches/{batch_id}/analyze
```

---

## Support and Development

For development setup, configuration, and deployment instructions, see:
- `README.md` - Project overview and navigation
- `QUICK_START.md` - Quick setup guide
- `DEPLOYMENT_GUIDE.md` - Deployment and operations

**Version**: 1.0  
**Last Updated**: November 2, 2025