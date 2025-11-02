# Enterprise Image Processing System - Quick Start Guide

This guide will help you get the enterprise image processing system up and running quickly.

## 🚀 Prerequisites

Before starting, ensure you have:

- **Python 3.8+** installed
- **PostgreSQL 12+** installed and running
- **Redis 6.0+** installed and running
- **Google Gemini AI API Key**

## 📦 Quick Installation

### 1. Clone and Setup

```bash
git clone <repository-url>
cd image-analyzer-enterprise

# Run automated setup
python setup.py --setup-dev
```

### 2. Configure Environment

```bash
# Copy example configuration
cp .env.example .env

# Edit .env with your settings
nano .env
```

**Required settings in `.env`:**
```env
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=imageprocessing
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Gemini AI API Key
GEMINI_API_KEYS=your_gemini_api_key_here

# Processing settings
CHUNK_SIZE=1000
MAX_CONCURRENT_BATCHES=5
MAX_WORKERS=4
```

### 3. Initialize Database

```bash
python setup.py --init-db
```

### 4. Verify Setup

```bash
python setup.py --health-check
```

### 5. Start Application

```bash
python run_server.py
```

The application will be available at: `http://localhost:5001`

## 🎯 First Batch Processing

### 1. Prepare Your CSV File

Create a CSV file with image URLs:
```csv
url
https://example.com/image1.jpg
https://example.com/image2.jpg
https://example.com/image3.jpg
```

Or download the template:
```bash
curl -O http://localhost:5001/export/template
```

### 2. Upload and Process

**Via Web Interface:**
1. Open `http://localhost:5001` in your browser
2. Drag and drop your CSV file
3. Enter a batch name (optional)
4. Check "Start processing immediately"
5. Click "Create Batch"

**Via API:**
```bash
curl -X POST http://localhost:5001/api/v1/batches \
  -F "file=@your_urls.csv" \
  -F "batch_name=My First Batch" \
  -F "auto_start=true"
```

### 3. Monitor Progress

**Web Dashboard:**
- Real-time progress updates
- Batch status and statistics
- Error monitoring

**API Monitoring:**
```bash
# Get batch status
curl http://localhost:5001/api/v1/batches/{batch_id}/status

# Get progress updates
curl http://localhost:5001/api/v1/batches/{batch_id}/progress
```

### 4. Export Results

**Web Interface:**
- Click the "Export" dropdown on batch detail page
- Choose format (CSV, JSON, Excel)
- Select filters if needed

**API Export:**
```bash
# CSV export
curl -O http://localhost:5001/export/batch/{batch_id}?format=csv

# JSON export
curl -O http://localhost:5001/export/batch/{batch_id}?format=json

# Filtered export (successful only)
curl -O http://localhost:5001/export/batch/{batch_id}?format=csv&success_only=true
```

## 🔧 Common Tasks

### Managing Batches

**Start a batch:**
```bash
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/start
```

**Pause processing:**
```bash
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/pause
```

**Resume processing:**
```bash
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/resume
```

**Cancel batch:**
```bash
curl -X POST http://localhost:5001/api/v1/batches/{batch_id}/cancel
```

### System Monitoring

**Check system health:**
```bash
curl http://localhost:5001/api/v1/health
```

**Get system statistics:**
```bash
curl http://localhost:5001/api/v1/system/stats
```

**View processing queue:**
```bash
# Check queue statistics in system stats
curl http://localhost:5001/api/v1/system/stats | jq '.data.queue_stats'
```

## ⚡ Performance Optimization

### For Large Scale Processing (15M+ URLs)

1. **Increase Workers:**
```env
MAX_WORKERS=8
MAX_CONCURRENT_BATCHES=10
```

2. **Add More API Keys:**
```env
GEMINI_API_KEYS=key1,key2,key3,key4
```

3. **Optimize Database:**
```sql
-- Increase connection pool
# In .env:
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=100
```

4. **Scale Redis:**
```env
REDIS_MAX_CONNECTIONS=200
```

### For Better Throughput

1. **Larger Chunks:**
```env
CHUNK_SIZE=2000
```

2. **More Concurrent Processing:**
```env
MAX_CONCURRENT_REQUESTS=10
```

3. **Optimize Timeouts:**
```env
REQUEST_TIMEOUT=45
RETRY_ATTEMPTS=5
```

## 🔍 Troubleshooting

### Common Issues

**Database Connection Error:**
```bash
# Check PostgreSQL service
sudo systemctl status postgresql

# Test connection
psql -h localhost -U postgres -d imageprocessing

# Reinitialize if needed
python setup.py --init-db --drop-db
```

**Redis Connection Error:**
```bash
# Check Redis service
redis-cli ping

# Restart if needed
sudo systemctl restart redis
```

**Slow Processing:**
- Check API key rate limits
- Add more API keys
- Increase workers
- Monitor system resources

**Memory Issues:**
- Reduce MAX_WORKERS
- Reduce CHUNK_SIZE
- Reduce MAX_CONCURRENT_BATCHES

### Debug Mode

**Run in debug mode:**
```bash
python run_server.py --debug
```

**Check logs:**
```bash
tail -f logs/enterprise_app.log
tail -f logs/processing.log
```

**Test individual components:**
```bash
# Test database only
python setup.py --health-check

# Test specific functionality
python test_enterprise_system.py --test database_connectivity
```

## 📊 Monitoring & Maintenance

### Daily Monitoring

1. **Check system status:**
   - Visit: `http://localhost:5001/system/status`
   - Check database and Redis connectivity
   - Monitor queue statistics

2. **Review batch progress:**
   - Monitor active batches
   - Check error rates
   - Review processing speeds

3. **Log monitoring:**
```bash
# Check for errors
grep ERROR logs/enterprise_app.log | tail -20

# Monitor processing
grep "Batch.*completed" logs/enterprise_app.log | tail -10
```

### Maintenance Tasks

**Weekly cleanup:**
```bash
# Clean up old completed batches (if needed)
# This should be done carefully in production

# Restart workers for fresh state
python -c "
import asyncio
from src.background_worker import worker_manager
asyncio.run(worker_manager.restart_workers())
"
```

**Database maintenance:**
```sql
-- Analyze tables for performance
ANALYZE processing_batches;
ANALYZE processing_chunks;
ANALYZE url_analysis_results;

-- Check database size
SELECT pg_size_pretty(pg_database_size('imageprocessing'));
```

## 🆘 Getting Help

### Support Resources

1. **System Health Check:**
   ```bash
   python setup.py --health-check
   ```

2. **Comprehensive Testing:**
   ```bash
   python test_enterprise_system.py
   ```

3. **API Documentation:**
   - Polling API: `http://localhost:5001/api/v1/`
   - Export API: `http://localhost:5001/api/v1/export/`

4. **Log Files:**
   - Application: `logs/enterprise_app.log`
   - Processing: `logs/processing.log`
   - Database: PostgreSQL logs
   - Redis: Redis logs

### Performance Benchmarks

**Expected Performance (single API key):**
- ~60 URLs per minute
- 15M URLs ≈ 173 days

**Scaling with multiple API keys:**
- 2 keys: ~86 days
- 4 keys: ~43 days
- 8 keys: ~22 days

**Memory Usage:**
- Base application: ~200MB
- Per active chunk: ~50MB
- Per worker: ~100MB

---

🎉 **You're all set!** Your enterprise image processing system is ready to handle millions of URLs efficiently.

For detailed documentation, see [README.md](README.md)