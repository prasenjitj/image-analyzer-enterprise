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

A scalable, production-ready image analysis system capable of processing millions of images with advanced queuing, batch management, and real-time monitoring.

## 🚀 Features

- **Massive Scale Processing**: Handle millions of image URLs efficiently  
- **Intelligent Batching**: Process images in configurable chunks with progress tracking
- **PostgreSQL + Redis**: Persistent storage with high-performance caching
- **Background Workers**: Parallel processing with automatic retry logic
- **Real-time Dashboard**: Live progress tracking and system metrics
- **Multi-format Export**: CSV, JSON, Excel exports with filtering
- **RESTful API**: Complete programmatic access to all features
- **Fault Tolerance**: Automatic error recovery and pause/resume support

## 📋 Quick Start (5 minutes)

For full, step-by-step setup with screenshots and troubleshooting, see QUICK_START.md.

### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- Redis 6+
- Google Gemini API keys

### Environment Variables

Key environment variables (full list in [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#required-environment-variables)):

```bash
# API Keys
GEMINI_API_KEYS=key1,key2,key3          # Comma-separated API keys

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/image_analyzer

# Redis
REDIS_URL=redis://localhost:6379/0

# Application
SECRET_KEY=your_secret_key_here
MAX_UPLOAD_SIZE=104857600               # 100MB in bytes
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
├── processor.py              # Image processing logic
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

## ⚡ Performance (Updated with Optimizations)

**Single API Key**: ~60 URLs/min | 15M URLs ≈ 173 days  
**4 API Keys (Optimized)**: ~240 URLs/min | 15M URLs ≈ 35 days  
**6+ API Keys (High Performance)**: ~350+ URLs/min | 15M URLs ≈ 24 days  
**Memory**: ~200MB base + optimized workers with memory monitoring

See [PERFORMANCE_OPTIMIZATION_GUIDE.md](docs/PERFORMANCE_OPTIMIZATION_GUIDE.md) for comprehensive optimization strategies and [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) for basic configuration tips.

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
