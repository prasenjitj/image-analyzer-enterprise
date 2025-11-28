# Enterprise Image Analyzer

A scalable, production-ready image analysis system for processing millions of images. Supports both OpenRouter AI and custom legacy API backends for maximum flexibility.

## Features

- **Massive Scale Processing**: Handle millions of image URLs efficiently
- **Flexible API Backends**: Switch between OpenRouter AI and custom/self-hosted APIs
- **OpenRouter Integration**: Uses Qwen 2.5 VL or custom presets for image analysis
- **Legacy API Support**: Connect to self-hosted vLLM or other inference servers
- **Intelligent Batching**: Configurable chunks with progress tracking
- **PostgreSQL + Redis**: Persistent storage with high-performance caching
- **Background Workers**: Parallel processing with automatic retry logic
- **Real-time Dashboard**: Live progress tracking and system metrics
- **Multi-format Export**: CSV, JSON, Excel exports with filtering
- **RESTful API**: Complete programmatic access
- **Fault Tolerance**: Automatic error recovery and pause/resume support

## Quick Start

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- Redis 6+
- OpenRouter API key OR legacy API endpoint

### Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 3. Initialize database
python setup.py --init-db

# 4. Verify setup
python setup.py --health-check

# 5. Start the application
python server/run_server.py
```

**Access Dashboard**: http://localhost:5001

### Environment Variables

```bash
# API Backend Selection (openrouter or legacy)
API_BACKEND=openrouter

# Option A: OpenRouter API (default)
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_PRESET=@preset/identify-storefront

# Option B: Legacy/Custom API
LEGACY_API_ENDPOINT=http://your-server:8000/generate
LEGACY_API_KEY=optional_key

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/image_analyzer

# Redis
REDIS_URL=redis://localhost:6379/0
```

See `.env.example` for all configuration options.

## Architecture

```
src/
├── enterprise_app.py          # Flask web server
├── processor.py               # OpenRouter image processing
├── batch_manager.py           # Batch orchestration
├── job_queue.py              # Redis queue management
├── database_models.py        # PostgreSQL schema
├── export_manager.py         # Export formats (CSV, Excel, JSON)
├── resilience.py             # Circuit breaker, rate limiting
└── enterprise_config.py      # Configuration management

server/
├── run_server.py             # Local development server
├── run_server_cloud.py       # Production/Cloud Run server
└── run_workers.py            # Background worker launcher
```

## Usage

### Upload and Process Images

**Via Web UI:**
1. Open http://localhost:5001
2. Upload CSV file with image URLs
3. Click "Create Batch"

**Via API:**
```bash
curl -X POST http://localhost:5001/api/v1/batches \
  -F "file=@urls.csv" \
  -F "batch_name=My Batch"
```

### CSV Format

```csv
Serial No.,Business Name,Phone Number,StoreFront Photo URL
1,ABC Grocery Store,+1-555-123-4567,https://example.com/storefront1.jpg
2,XYZ Restaurant,+1-555-987-6543,https://example.com/storefront2.jpg
```

### Monitor Progress

```bash
curl http://localhost:5001/api/v1/batches/{batch_id}/status
```

### Export Results

```bash
curl -O "http://localhost:5001/api/v1/batch-data/export?format=csv"
```

## Documentation

| Document | Purpose |
|----------|---------|
| [QUICK_START.md](docs/QUICK_START.md) | Detailed setup guide |
| [API_DOCUMENTATION.md](docs/API_DOCUMENTATION.md) | API reference |
| [DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) | Production deployment |

## GCP Deployment

```bash
# Complete automated deployment
./scripts/deploy_all.sh [VM_IP] [PROJECT_ID] [REGION]
```

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src
```

## Troubleshooting

```bash
# Check system health
python setup.py --health-check

# Test PostgreSQL
psql -h localhost -U postgres -d imageprocessing

# Test Redis
redis-cli ping
```

## License

MIT License - see [LICENSE](LICENSE) for details.