# Configuration and Deployment Guide

## Environment Configuration

### Required Environment Variables

```bash
# Gemini (Vision) API Keys
# Prefer using GEMINI_API_KEYS (comma-separated for multiple keys)
GEMINI_API_KEYS=key1,key2,key3
# Legacy: GOOGLE_API_KEY/GEMINI_API_KEY supported if present
GOOGLE_API_KEY=your_google_vision_api_key

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/image_analyzer
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=30
DATABASE_ECHO=false

# Redis Configuration  
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=your_redis_password  # Optional
REDIS_DB=0

# Processing Configuration (Performance Optimized)
CHUNK_SIZE=2000                    # URLs per chunk (increased from 1000)
MAX_CONCURRENT_BATCHES=20          # Maximum active batches (increased from 5)
MAX_CONCURRENT_CHUNKS=10           # Chunks per batch (increased from 3)
MAX_CONCURRENT_WORKERS=100         # Background workers (increased from 50)
MAX_CONCURRENT_REQUESTS=25         # Concurrent requests per worker (new)
REQUESTS_PER_MINUTE=200            # Rate limit with multiple API keys (increased from 55)

# Database Performance Configuration (New)
DATABASE_POOL_SIZE=200             # Connection pool size
DATABASE_MAX_OVERFLOW=300          # Max overflow connections
DATABASE_POOL_TIMEOUT=30           # Connection timeout
DATABASE_POOL_RECYCLE=1800         # Connection recycle time

# Redis Performance Configuration (New)
REDIS_MAX_CONNECTIONS=1000         # Max Redis connections
REDIS_SOCKET_TIMEOUT=10            # Socket timeout

# Memory and Performance (New)
MEMORY_LIMIT_GB=8                  # Memory limit for workers
GC_FREQUENCY=100                   # Garbage collection frequency
ENABLE_MEMORY_MONITORING=true     # Enable memory monitoring

# Application Configuration
SECRET_KEY=your_secret_key_here
MAX_UPLOAD_SIZE=104857600          # 100MB in bytes
UPLOAD_DIR=./uploads
EXPORT_DIR=./exports
LOG_DIR=./logs
TEMP_DIR=./temp

# Development Settings
DEVELOPMENT_MODE=false
ENABLE_DEBUG_LOGGING=false
```

### Environment File (.env)
Create a `.env` file in the project root:

```bash
# Copy example configuration
cp .env.example .env

# Edit with your settings
nano .env
```

## Database Setup

### PostgreSQL Installation

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### macOS
```bash
brew install postgresql
brew services start postgresql
```

#### Docker
```bash
docker run --name postgres-db \
  -e POSTGRES_DB=image_analyzer \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -p 5432:5432 \
  -d postgres:13
```

### Database Setup
```bash
# Create database
sudo -u postgres psql
CREATE DATABASE image_analyzer;
CREATE USER analyzer_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE image_analyzer TO analyzer_user;
\q

# Test connection
psql -h localhost -U analyzer_user -d image_analyzer -c "SELECT 1;"
```

## Database Maintenance and Data Management

### Database Management Script

The application includes two database management utilities:

#### Python Script (Recommended)
Requires Python dependencies:
```bash
pip install -r requirements.txt
python scripts/db_manage.py stats
```

#### Shell Script (Alternative)
Direct SQL operations, no Python dependencies required:
```bash
# Configure database connection variables in the script first
./scripts/db_maintenance.sh stats
./scripts/db_maintenance.sh clear-old 30
./scripts/db_maintenance.sh backup
```

**Available operations:**
```bash
# Show database statistics
./scripts/db_maintenance.sh stats

# Clear batches older than 30 days
./scripts/db_maintenance.sh clear-old 30

# Clear failed/cancelled batches
./scripts/db_maintenance.sh clear-failed

# Clear ALL data (dangerous!)
./scripts/db_maintenance.sh clear-all

# Optimize database (VACUUM, ANALYZE)
./scripts/db_maintenance.sh optimize

# Create backup
./scripts/db_maintenance.sh backup ./backups
```

### Manual Database Operations

#### View Database Statistics
```sql
-- Connect to database
psql -h localhost -U analyzer_user -d image_analyzer

-- Count records in each table
SELECT 'processing_batches' as table_name, COUNT(*) as count FROM processing_batches
UNION ALL
SELECT 'processing_chunks', COUNT(*) FROM processing_chunks
UNION ALL
SELECT 'url_analysis_results', COUNT(*) FROM url_analysis_results;

-- View batch status breakdown
SELECT status, COUNT(*) as count
FROM processing_batches
GROUP BY status
ORDER BY count DESC;

-- Find oldest batch
SELECT batch_id, batch_name, created_at
FROM processing_batches
ORDER BY created_at ASC
LIMIT 1;
```

#### Clear Old Data (Safe Method)
```sql
-- Clear batches older than 30 days (adjust date as needed)
-- First, delete associated analysis results
DELETE FROM url_analysis_results
WHERE batch_id IN (
    SELECT batch_id FROM processing_batches
    WHERE created_at < NOW() - INTERVAL '30 days'
);

-- Then delete chunks
DELETE FROM processing_chunks
WHERE batch_id IN (
    SELECT batch_id FROM processing_batches
    WHERE created_at < NOW() - INTERVAL '30 days'
);

-- Finally delete the batches
DELETE FROM processing_batches
WHERE created_at < NOW() - INTERVAL '30 days';
```

#### Clear Failed/Cancelled Batches
```sql
-- Delete failed/cancelled batches and their associated data
-- First, delete associated analysis results
DELETE FROM url_analysis_results
WHERE batch_id IN (
    SELECT batch_id FROM processing_batches
    WHERE status IN ('failed', 'cancelled')
);

-- Then delete chunks
DELETE FROM processing_chunks
WHERE batch_id IN (
    SELECT batch_id FROM processing_batches
    WHERE status IN ('failed', 'cancelled')
);

-- Finally delete the batches
DELETE FROM processing_batches
WHERE status IN ('failed', 'cancelled');
```

#### Clear All Data (Dangerous - Use with Caution)
```sql
-- ⚠️  WARNING: This will delete ALL data permanently!
-- Delete in correct order to respect foreign key constraints
DELETE FROM url_analysis_results;
DELETE FROM processing_chunks;
DELETE FROM processing_batches;
```

#### Reset Database Tables (Nuclear Option)
```sql
-- ⚠️  EXTREME WARNING: This will DROP ALL TABLES and DATA!
-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS url_analysis_results;
DROP TABLE IF EXISTS processing_chunks;
DROP TABLE IF EXISTS processing_batches;

-- Recreate tables (run the application initialization)
-- python -c "from src.database_models import init_database; init_database()"
```

### Database Backup Before Clearing

**Always backup before clearing data:**

```bash
#!/bin/bash
# backup_before_clear.sh
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

echo "📦 Creating database backup..."
pg_dump -h localhost -U analyzer_user image_analyzer | \
  gzip > $BACKUP_DIR/pre_clear_backup_$TIMESTAMP.sql.gz

echo "✅ Backup created: $BACKUP_DIR/pre_clear_backup_$TIMESTAMP.sql.gz"
echo "💡 Restore with: gunzip < $BACKUP_DIR/pre_clear_backup_$TIMESTAMP.sql.gz | psql -h localhost -U analyzer_user image_analyzer"
```

### Automated Cleanup Script

Create a maintenance script for regular cleanup:

```bash
#!/bin/bash
# db_maintenance.sh
# Run this script weekly/monthly for database maintenance

echo "🧹 Starting database maintenance..."

# Backup before cleanup
./backup_before_clear.sh

# Clear old batches (older than 90 days)
echo "🗑️  Clearing batches older than 90 days..."
python scripts/db_manage.py clear-old --days 90 --confirm

# Clear failed batches
echo "🗑️  Clearing failed/cancelled batches..."
python scripts/db_manage.py clear-failed --confirm

# Vacuum and analyze for performance
echo "🔧 Optimizing database..."
psql -h localhost -U analyzer_user -d image_analyzer -c "VACUUM ANALYZE;"

echo "✅ Database maintenance completed!"
```

#### Schedule Automated Maintenance

```bash
# Add to crontab for weekly maintenance (run as analyzer user)
sudo -u analyzer crontab -e

# Add this line for weekly maintenance on Sundays at 2 AM:
# 0 2 * * 0 /opt/image-analyzer/db_maintenance.sh >> /opt/image-analyzer/logs/db_maintenance.log 2>&1
```

### Database Performance After Clearing

After clearing large amounts of data, optimize the database:

```bash
# Vacuum full (reclaims space, may take time)
psql -h localhost -U analyzer_user -d image_analyzer -c "VACUUM FULL;"

# Reindex tables (rebuilds indexes)
psql -h localhost -U analyzer_user -d image_analyzer -c "REINDEX DATABASE image_analyzer;"

# Update table statistics
psql -h localhost -U analyzer_user -d image_analyzer -c "ANALYZE;"
```

### Monitoring Database Size

```bash
# Check database size
psql -h localhost -U analyzer_user -d image_analyzer -c "
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Monitor growth over time
psql -h localhost -U analyzer_user -d image_analyzer -c "
SELECT
    date(created_at) as day,
    COUNT(*) as batches_created,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as batches_completed
FROM processing_batches
WHERE created_at >= NOW() - INTERVAL '30 days'
GROUP BY date(created_at)
ORDER BY day DESC;
"
```

## Redis Setup

### Redis Installation

#### Ubuntu/Debian
```bash
sudo apt install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### macOS
```bash
brew install redis
brew services start redis
```

#### Docker
```bash
docker run --name redis-server \
  -p 6379:6379 \
  -d redis:7-alpine
```

### Redis Configuration
```bash
# Test Redis connection
redis-cli ping
# Should return: PONG

# Optional: Set password
redis-cli
CONFIG SET requirepass your_password
CONFIG REWRITE
```

## Application Deployment

### Development Setup

```bash
# Clone repository
git clone <repository_url>
cd image-analyzer-enterprise

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create directories
mkdir -p uploads exports logs temp

# Initialize database
python -c "from src.database_models import init_database; init_database()"

# Start application
python run_server.py
```

### Production Deployment

#### Option 1: Systemd Service

Create service file: `/etc/systemd/system/image-analyzer.service`

```ini
[Unit]
Description=Image Analyzer Enterprise
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=analyzer
Group=analyzer
WorkingDirectory=/opt/image-analyzer
Environment=PATH=/opt/image-analyzer/venv/bin
ExecStart=/opt/image-analyzer/venv/bin/python run_server.py --host 0.0.0.0 --port 5001
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable image-analyzer
sudo systemctl start image-analyzer
sudo systemctl status image-analyzer
```

#### Option 2: Docker Deployment

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:13
    environment:
      POSTGRES_DB: image_analyzer
      POSTGRES_USER: analyzer_user
      POSTGRES_PASSWORD: your_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"

  app:
    build: .
    ports:
      - "5001:5001"
    environment:
      - DATABASE_URL=postgresql://analyzer_user:your_password@postgres:5432/image_analyzer
      - REDIS_URL=redis://redis:6379/0
      - GOOGLE_API_KEY=your_api_key
    volumes:
      - ./uploads:/app/uploads
      - ./exports:/app/exports
      - ./logs:/app/logs
    depends_on:
      - postgres
      - redis

  worker:
    build: .
    command: python run_workers.py
    environment:
      - DATABASE_URL=postgresql://analyzer_user:your_password@postgres:5432/image_analyzer
      - REDIS_URL=redis://redis:6379/0
      - GOOGLE_API_KEY=your_api_key
    depends_on:
      - postgres
      - redis
    deploy:
      replicas: 3

volumes:
  postgres_data:
  redis_data:
```

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p uploads exports logs temp

# Initialize database on startup
RUN python -c "from src.database_models import init_database; init_database()" || true

EXPOSE 5001

CMD ["python", "run_server.py", "--host", "0.0.0.0", "--port", "5001"]
```

Deploy with Docker:
```bash
docker-compose up -d
```

#### Option 3: Gunicorn + Nginx

Install Gunicorn:
```bash
pip install gunicorn
```

Create `gunicorn.conf.py`:
```python
bind = "127.0.0.1:5001"
workers = 4
worker_class = "sync"
worker_connections = 1000
timeout = 300
keepalive = 2
max_requests = 1000
max_requests_jitter = 100
preload_app = True
```

Start with Gunicorn:
```bash
gunicorn --config gunicorn.conf.py src.enterprise_app:enterprise_app
```

Nginx configuration (`/etc/nginx/sites-available/image-analyzer`):
```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }

    location /static {
        alias /opt/image-analyzer/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## Monitoring and Logging

### Log Configuration

Update logging in `src/enterprise_app.py`:
```python
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'logs/enterprise_app.log',
            maxBytes=10485760,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)
```

### Health Monitoring

Create health check script (`health_check.py`):
```python
#!/usr/bin/env python3
import requests
import sys

def health_check():
    try:
        response = requests.get('http://localhost:5001/api/v1/health', timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('success') and data['data']['status'] == 'healthy':
                print("✅ Application is healthy")
                return 0
        print("❌ Application is unhealthy")
        return 1
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(health_check())
```

### Process Monitoring with Supervisor

Install Supervisor:
```bash
sudo apt install supervisor
```

Create config (`/etc/supervisor/conf.d/image-analyzer.conf`):
```ini
[program:image-analyzer-web]
command=/opt/image-analyzer/venv/bin/gunicorn --config gunicorn.conf.py src.enterprise_app:enterprise_app
directory=/opt/image-analyzer
user=analyzer
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/image-analyzer-web.err.log
stdout_logfile=/var/log/supervisor/image-analyzer-web.out.log

[program:image-analyzer-workers]
command=/opt/image-analyzer/venv/bin/python run_workers.py
directory=/opt/image-analyzer
user=analyzer
autostart=true
autorestart=true
numprocs=3
process_name=%(program_name)s_%(process_num)02d
stderr_logfile=/var/log/supervisor/image-analyzer-worker.err.log
stdout_logfile=/var/log/supervisor/image-analyzer-worker.out.log
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start all
```

## Performance Optimization

### Database Optimization

PostgreSQL tuning (`postgresql.conf`):
```ini
# Memory settings
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB

# Connection settings
max_connections = 100

# Checkpoint settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB

# Query planner
random_page_cost = 1.1
```

### Redis Optimization

Redis tuning (`redis.conf`):
```ini
# Memory settings
maxmemory 1gb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000

# Network
tcp-keepalive 300
timeout 0
```

### Application Optimization (Updated for High Performance)

Environment variables for production:
```bash
# High-performance worker configuration
MAX_CONCURRENT_WORKERS=100         # Increased for better throughput
MAX_CONCURRENT_BATCHES=20          # Support more simultaneous batches
MAX_CONCURRENT_REQUESTS=25         # Higher per-worker concurrency
CHUNK_SIZE=2000                    # Larger chunks for efficiency

# Optimized database connections
DATABASE_POOL_SIZE=200             # Increased pool size
DATABASE_MAX_OVERFLOW=300          # Higher overflow capacity
DATABASE_POOL_TIMEOUT=30           # Connection timeout
DATABASE_POOL_RECYCLE=1800         # Connection lifecycle management

# Redis optimization
REDIS_MAX_CONNECTIONS=1000         # Support high concurrency
REDIS_SOCKET_TIMEOUT=10            # Optimized timeout

# Rate limiting with multiple API keys
REQUESTS_PER_MINUTE=200            # Higher throughput with multiple keys
GEMINI_API_KEYS=key1,key2,key3,key4  # Use multiple API keys

# Memory management
MEMORY_LIMIT_GB=8                  # Memory limit for workers
GC_FREQUENCY=100                   # Garbage collection frequency
ENABLE_MEMORY_MONITORING=true     # Monitor memory usage
```

> **Note**: For comprehensive performance optimization strategies, configuration tuning, and advanced deployment patterns, see the [Performance Optimization Guide](PERFORMANCE_OPTIMIZATION_GUIDE.md).

## Security Considerations

### Basic Security Setup

1. **API Key Security**:
```bash
# Store API keys securely
export GOOGLE_API_KEY="$(cat /etc/secrets/google_api_key)"
```

2. **Database Security**:
```sql
-- Create restricted user
CREATE USER app_user WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE image_analyzer TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
```

3. **Firewall Configuration**:
```bash
# Allow only necessary ports
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP
sudo ufw allow 443   # HTTPS
sudo ufw deny 5432   # PostgreSQL (internal only)
sudo ufw deny 6379   # Redis (internal only)
sudo ufw enable
```

4. **SSL Configuration** (with Let's Encrypt):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## Backup and Recovery

### Database Backup
```bash
#!/bin/bash
# backup_db.sh
BACKUP_DIR="/backups/postgres"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

pg_dump -h localhost -U analyzer_user image_analyzer | \
  gzip > $BACKUP_DIR/image_analyzer_$DATE.sql.gz

# Keep only last 7 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
```

### Application Backup
```bash
#!/bin/bash
# backup_app.sh
BACKUP_DIR="/backups/app"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

tar -czf $BACKUP_DIR/uploads_$DATE.tar.gz uploads/
tar -czf $BACKUP_DIR/exports_$DATE.tar.gz exports/
tar -czf $BACKUP_DIR/logs_$DATE.tar.gz logs/
```

## Troubleshooting

### Common Issues

1. **Database Connection Issues**:
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Check connections
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity;"

# Reset connections
sudo systemctl restart postgresql
```

2. **Redis Connection Issues**:
```bash
# Check Redis status
redis-cli ping

# Check memory usage
redis-cli info memory

# Clear Redis cache
redis-cli flushall
```

3. **High Memory Usage**:
```bash
# Monitor memory
free -h
htop

# Adjust chunk size
export CHUNK_SIZE=500
```

4. **Slow Processing**:
```bash
# Check API limits
curl http://localhost:5001/api/v1/system/stats

# Monitor queue
curl http://localhost:5001/admin/queue/status

# Clean stuck jobs
curl -X POST http://localhost:5001/admin/queue/cleanup \
  -H "Content-Type: application/json" \
  -d '{"max_age_hours": 1}'
```

### Log Analysis
```bash
# View application logs
tail -f logs/enterprise_app.log

# Check error patterns
grep -i error logs/enterprise_app.log | tail -20

# Monitor performance
grep "processing rate" logs/enterprise_app.log
```

## Scaling Considerations

### Horizontal Scaling
- Use multiple worker instances with shared database/Redis
- Implement load balancing with Nginx or HAProxy
- Consider container orchestration with Kubernetes

### Vertical Scaling
- Increase server resources (CPU, RAM)
- Optimize database configuration for larger datasets
- Use faster storage (SSD) for database and cache

### Database Scaling
- Implement read replicas for export operations
- Consider partitioning large tables by date
- Use connection pooling (PgBouncer)

This completes the comprehensive API documentation for your image analyzer enterprise application!