# Enterprise Image Analyzer - Production Ready

> **📋 Status Update - Repository Restructuring Complete ✅**  
> All issues from the recent repository restructuring have been identified and fixed:
> - ✅ Server startup path issues resolved  
> - ✅ Missing directories auto-created
> - ✅ Security vulnerabilities patched
> - ✅ All functionality tested and verified working
> 
> **🚀 Ready to Use**: `python3 server/run_server.py` now starts successfully!  
> See [UPDATED_QUICK_START_GUIDE.md](UPDATED_QUICK_START_GUIDE.md) for details.

A scalable, production-ready image analysis system capable of processing millions of images with advanced queuing, batch management, and real-time monitoring. Uses external AI API endpoints for image analysis instead of local OCR processing.

## 🚀 Features

- **Massive Scale Processing**: Handle millions of image URLs efficiently  
- **Intelligent Batching**: Process images in configurable chunks with progress tracking
- **PostgreSQL + Redis**: Persistent storage with high-performance caching
- **Background Workers**: Parallel processing with automatic retry logic
- **Real-time Dashboard**: Live progress tracking and system metrics
- **Multi-format Export**: CSV, JSON, Excel exports with filtering
- **RESTful API**: Complete programmatic access to all features
- **Fault Tolerance**: Automatic error recovery and pause/resume support
- **External AI Integration**: Uses configurable API endpoints for image analysis

## 📋 Quick Start (5 minutes)

For full, step-by-step setup with screenshots and troubleshooting, see QUICK_START.md.

### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- Redis 6+
- External AI API endpoint (configured via environment variables)

### Environment Variables

Key environment variables (full list in [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#required-environment-variables)):

```bash
# External AI API Configuration
API_ENDPOINT_URL=http://your-api-endpoint:8000/generate  # External AI API endpoint

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/image_analyzer

# Redis
REDIS_URL=redis://localhost:6379/0

# Application
SECRET_KEY=your_secret_key_here
MAX_UPLOAD_SIZE=104857600               # 100MB in bytes
REQUEST_TIMEOUT=60                      # API request timeout in seconds
# Optional: split large CSV uploads into multiple batches
# Set MAX_BATCH_SIZE to change the split threshold (default: 5000)
MAX_BATCH_SIZE=5000
```

### Setup
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL, Redis, and API credentials

# 3. Initialize database
python setup.py --init-db

# 4. Verify setup
python setup.py --health-check

# 5. Start the application (Local Development)
python3 server/run_server.py

# For production/container deployment
python3 server/run_server_cloud.py

# In another terminal: Start background workers (optional - auto-started)
python server/run_workers.py
```

**Access Dashboard**: http://localhost:5001

## 📖 Documentation

| Document | Purpose |
|----------|---------|
| **[QUICK_START.md](docs/QUICK_START.md)** | Detailed setup and first batch guide |
| **[API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md)** | Complete API reference |
| **[DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)** | Production deployment instructions |
| **[GCP_DEPLOYMENT_GUIDE.md](docs/GCP_DEPLOYMENT_GUIDE.md)** | Google Cloud Platform deployment guide |
| **[PERFORMANCE_OPTIMIZATION_GUIDE.md](docs/PERFORMANCE_OPTIMIZATION_GUIDE.md)** | Performance optimization and scaling strategies |
| **[GCP_FREE_DEPLOYMENT_GUIDE.md](docs/GCP_FREE_DEPLOYMENT_GUIDE.md)** | Free tier GCP deployment guide |

## 🚀 Deployment Scripts

For quick GCP deployment, use the provided bash scripts:

```bash
# Complete automated deployment
./scripts/deploy_all.sh [VM_IP] [PROJECT_ID] [REGION]

# Or run individual steps:
./scripts/create_env_yaml.sh [VM_IP] [PROJECT_ID]
./scripts/create_dockerfiles.sh
./scripts/setup_vpc_connector.sh [PROJECT_ID] [REGION]
./scripts/build_and_deploy_server.sh [PROJECT_ID] [REGION]
./scripts/build_and_deploy_worker.sh [PROJECT_ID] [REGION]
```

## 🎯 Common Tasks

### Upload and Process Images
```bash
# Via Web UI
1. Open http://localhost:5001
2. Drag & drop CSV file with URLs
3. Click "Create Batch"

# Via API
curl -X POST http://localhost:5001/api/v1/batches \
  -F "file=@urls.csv" \
  -F "batch_name=My Batch"
```

Note: CSV files larger than MAX_BATCH_SIZE (default 5000) will be split into multiple batches automatically. Each split batch is treated independently and has its own chunks, processing lifecycle and batch_id. All batches created from the same CSV share a parent_batch_id for tracking.

### Monitor Progress
```bash
# Web dashboard: http://localhost:5001
# Or via API:
curl http://localhost:5001/api/v1/batches/{batch_id}/status
```

### Export Results
```bash
# Web UI: Click Export dropdown on batch detail page
# Or via API:
curl -O "http://localhost:5001/api/v1/batch-data/export?format=csv"
```

## 🏗️ Architecture

```
src/
├── enterprise_app.py          # Flask web server
├── background_worker.py       # Batch processing workers
├── batch_manager.py           # Batch orchestration
├── job_queue.py              # Redis queue management
├── export_api.py             # Export functionality
├── polling_api.py            # Real-time status API
├── database_models.py        # PostgreSQL schema
├── export_manager.py         # Export formats
├── cache.py                  # Caching layer
├── processor.py              # External API-based image processing
└── enterprise_config.py      # Configuration management

server/
├── run_server.py             # Local development server
├── run_server_cloud.py       # Container/Cloud Run server
├── run_workers.py            # Background worker launcher
├── run_worker_cloud.py       # Cloud worker launcher
└── run_worker_http.py        # HTTP worker service

scripts/
├── deploy_all.sh             # Complete deployment automation
├── build_and_deploy_server.sh # Server deployment
├── build_and_deploy_worker.sh # Worker deployment
├── create_env_yaml.sh        # Environment configuration
└── setup_vpc_connector.sh    # VPC network setup

templates/
├── modern_enterprise_dashboard.html  # Main UI
├── modern_admin_dashboard.html       # Admin panel
├── modern_system_status.html         # System metrics
└── shared-ui-components.css          # Shared styles
```

## 📦 CSV Splitting (new feature)

When you upload a CSV file with more records than the configured `MAX_BATCH_SIZE` (default 5000), the system automatically splits the CSV into multiple batches. Each split becomes an independent batch with its own chunks, queue jobs, and lifecycle. All split batches are linked by a `parent_batch_id` so you can track or aggregate progress across the original CSV upload.

Key points:
- The split threshold is controlled by the `MAX_BATCH_SIZE` environment variable (default 5000).
- Each new batch gets a `batch_id` and a human-friendly `batch_name` such as `MyBatch_Part1of3`.
- You can manage each split batch independently (pause/resume/retry/cancel/export).

Example: CSV with 12,500 records, `MAX_BATCH_SIZE=5000` => creates 3 batches:

- Part1of3 — 5000 records
- Part2of3 — 5000 records
- Part3of3 — 2500 records

API endpoints useful for split batches:

- DELETE /api/v1/batches/<batch_id>
  - Delete a single batch (same as batch_manager.delete_batch). Example:
    ```bash
    curl -i -X DELETE "http://127.0.0.1:5001/api/v1/batches/<BATCH_ID>"
    ```

- GET /api/v1/batches/related/<batch_id>
  - Returns the list of batches created from the same CSV (all children that share the same parent_batch_id).

- GET /api/v1/batches/parent/<parent_batch_id>/status
  - Aggregated status across all split batches (total urls, processed counts, success rates, per-batch status).

Storage / DB note:
The split-batch feature adds three new columns to the `processing_batches` table:

```sql
ALTER TABLE processing_batches
ADD COLUMN parent_batch_id UUID,
ADD COLUMN batch_sequence INTEGER DEFAULT 1,
ADD COLUMN total_split_batches INTEGER DEFAULT 1;
```

Apply this change before using split-batching in production (or create an Alembic migration to add these columns).


## ⚡ Performance (API-Based Processing)

**Processing Rates** (based on external API performance):
- **Standard Configuration**: ~100-200 URLs/minute (depends on external API response times)
- **Optimized Setup**: ~300+ URLs/minute with proper caching and error handling
- **Concurrent Workers**: Configurable background workers for parallel processing
- **Memory**: ~200MB base + optimized workers with memory monitoring

Performance depends on the external API endpoint response times and network conditions. The system includes automatic retry logic and timeout handling for reliability.

## 💰 Cost Estimation

### Cost Assumptions & Methodology

**Processing Rates** (based on external API performance):
- **Standard Configuration**: ~100-200 URLs/minute
- **Optimized Setup**: ~300+ URLs/minute with proper caching

**Cost Components**:
- **External API Costs**: Depends on your API provider pricing
- **Infrastructure**: PostgreSQL, Redis, and compute resources
- **Storage**: Database storage for results and caching

**Assumptions**:
- External API costs vary by provider
- Infrastructure costs based on cloud provider pricing
- 70% success rate (30% retries due to network/API issues)

### Cost Optimization Strategies

**Reduce API Costs**:
- Implement result caching (reduce duplicate API calls)
- Batch requests efficiently to minimize retries
- Monitor API usage and optimize for cost efficiency
- Use appropriate timeout and retry settings

**Infrastructure Costs**:
- **Development/Testing**: Minimal costs using free tier resources
- **Small Production**: <$50/month for moderate usage
- **Enterprise**: Scale based on processing volume and storage needs

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_enterprise_system.py -v

# With coverage
python -m pytest tests/ --cov=src
```

## 🔧 Troubleshooting

**Database Connection Error**
```bash
psql -h localhost -U postgres -d imageprocessing
# Should connect without errors
```

**Redis Connection Error**
```bash
redis-cli ping
# Should return: PONG
```

**Check System Health**
```bash
python setup.py --health-check
```

For more help, see [QUICK_START.md](QUICK_START.md) troubleshooting section.

## 📞 Support

- **System Status**: http://localhost:5001/system/status
- **Health Check**: `python setup.py --health-check`
- **Logs**: `logs/enterprise_app.log`
- **API Docs**: [API_DOCUMENTATION.md](API_DOCUMENTATION.md)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
