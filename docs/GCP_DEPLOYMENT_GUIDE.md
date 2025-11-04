# GCP Cloud Functions Deployment Guide

## Overview

This guide provides step-by-step instructions to deploy the Enterprise Image Analyzer to Google Cloud Platform using Cloud Functions with Docker containers.

## Prerequisites

## Prerequisites

- Google Cloud Project with billing enabled (free trial credits work)
- `gcloud` CLI installed and authenticated
- Docker installed locally
- PostgreSQL database (choose one):
  - Managed: Cloud SQL (paid, simple)
  - Free tier: Self-managed on Compute Engine e2-micro
  - External: Supabase/Neon (free tier)
- Redis (choose one):
  - Managed: Memorystore (paid)
  - Free tier: Self-managed on Compute Engine e2-micro
  - External: Redis Cloud (free tier)
- Google Cloud Storage bucket for uploads/exports

## 1. Set Up GCP Resources

Choose the database/cache option that fits your cost and ops preferences. You can mix-and-match:

- Option A (Managed): Cloud SQL + Memorystore
- Option B (Free tier): Self-managed PostgreSQL + Redis on Compute Engine e2-micro
- Option C (Free/external): Supabase/Neon PostgreSQL + Redis Cloud

### Option A — Managed: Create Cloud SQL PostgreSQL Instance

### Create Cloud SQL PostgreSQL Instance
```bash
gcloud sql instances create image-analyzer-db \
  --database-version=POSTGRES_13 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --root-password=YOUR_ROOT_PASSWORD
### Option A — Managed: Create Memorystore Redis Instance

### Create Database
```bash
gcloud sql databases create image_analyzer \
  --instance=image-analyzer-db
```

### Create Memorystore Redis Instance
```bash
gcloud redis instances create image-analyzer-redis \
  --size=1 \
``` 

### Option B — Free Tier: Self-managed PostgreSQL + Redis on Compute Engine

Provision two e2-micro VMs (free tier eligible) in the same region/VPC as your serverless resources:

```bash
# PostgreSQL VM
gcloud compute instances create pg-vm \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --tags=postgres \
  --region=us-central1 \
  --zone=us-central1-a

# Redis VM
gcloud compute instances create redis-vm \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --tags=redis \
  --region=us-central1 \
  --zone=us-central1-a
```

Install and configure PostgreSQL and Redis:

```bash
# SSH into PostgreSQL VM
gcloud compute ssh pg-vm --zone us-central1-a --command '
  sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib && 
  sudo -u postgres psql -c "CREATE USER analyzer_user WITH PASSWORD \"YOUR_DB_PASSWORD\";" && 
  sudo -u postgres psql -c "CREATE DATABASE image_analyzer OWNER analyzer_user;" && 
  sudo sed -i "s/^#*listen_addresses.*/listen_addresses = '*' /" /etc/postgresql/*/main/postgresql.conf && 
  echo "host all all 10.0.0.0/8 md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf && 
  sudo systemctl restart postgresql
'

# SSH into Redis VM
gcloud compute ssh redis-vm --zone us-central1-a --command '
  sudo apt-get update && sudo apt-get install -y redis-server && 
  sudo sed -i "s/^bind .*/bind 0.0.0.0/" /etc/redis/redis.conf && 
  sudo sed -i "s/^# requirepass .*/requirepass YOUR_REDIS_PASSWORD/" /etc/redis/redis.conf && 
  sudo systemctl restart redis-server
'
```

Restrict access to Serverless VPC Connector ranges only:

```bash
# Allow PostgreSQL from VPC connector CIDR (example 10.8.0.0/28)
gcloud compute firewall-rules create allow-postgres-from-serverless \
  --allow=tcp:5432 --target-tags=postgres --source-ranges=10.8.0.0/28

# Allow Redis from VPC connector CIDR
gcloud compute firewall-rules create allow-redis-from-serverless \
  --allow=tcp:6379 --target-tags=redis --source-ranges=10.8.0.0/28
```

Get internal IPs for env vars:

```bash
gcloud compute instances describe pg-vm --zone us-central1-a --format='value(networkInterfaces[0].networkIP)'
gcloud compute instances describe redis-vm --zone us-central1-a --format='value(networkInterfaces[0].networkIP)'
```

### Option C — External Free: Supabase/Neon + Redis Cloud

Use free-tier managed services with public endpoints:

- Create a database in Supabase or Neon; obtain the Postgres connection string (enable SSL).
- Create a free Redis instance in Redis Cloud; obtain the rediss URL with password.

Example connection strings for environment variables:

```text
# Supabase/Neon (ensure sslmode=require)
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require

# Redis Cloud (TLS)
REDIS_URL=rediss://default:PASSWORD@HOST:PORT
```
  --region=us-central1 \
Create a `.env.yaml` file for Cloud Functions environment variables (pick the matching values for your option):
```

# Option A (Cloud SQL + Memorystore): use instance IPs or private connectors
# DATABASE_URL: postgresql://postgres:YOUR_PASSWORD@YOUR_CLOUD_SQL_IP:5432/image_analyzer
# REDIS_URL: redis://YOUR_MEMSTORE_IP:6379/0

# Option B (Compute Engine internal IPs):
# Replace with internal IPs from pg-vm and redis-vm
# DATABASE_URL: postgresql://analyzer_user:YOUR_DB_PASSWORD@10.x.x.x:5432/image_analyzer
# REDIS_URL: redis://:YOUR_REDIS_PASSWORD@10.y.y.y:6379/0

# Option C (Supabase/Neon + Redis Cloud):
# DATABASE_URL: postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require
# REDIS_URL: rediss://default:PASSWORD@HOST:PORT
gsutil mb -p YOUR_PROJECT_ID -c STANDARD -l us-central1 gs://image-analyzer-uploads
gsutil mb -p YOUR_PROJECT_ID -c STANDARD -l us-central1 gs://image-analyzer-exports
```

## 2. Configure Environment Variables (Performance Optimized)

Create a `.env.yaml` file for Cloud Functions environment variables:

```yaml
# Database Configuration
DATABASE_URL: postgresql://postgres:YOUR_PASSWORD@YOUR_CLOUD_SQL_IP:5432/image_analyzer
DATABASE_POOL_SIZE: 200
DATABASE_MAX_OVERFLOW: 300
DATABASE_POOL_TIMEOUT: 30
DATABASE_POOL_RECYCLE: 1800

# Redis Configuration
REDIS_URL: redis://YOUR_REDIS_IP:6379/0
REDIS_MAX_CONNECTIONS: 1000
REDIS_SOCKET_TIMEOUT: 10

# API Configuration
GEMINI_API_KEYS: key1,key2,key3,key4  # Multiple keys for better performance
SECRET_KEY: your-secret-key-here

# Storage Configuration
UPLOAD_BUCKET: gs://image-analyzer-uploads
EXPORT_BUCKET: gs://image-analyzer-exports
MAX_UPLOAD_SIZE: 209715200  # 200MB for larger batches

# Performance Optimization
CHUNK_SIZE: 2000  # Increased from 1000
MAX_CONCURRENT_BATCHES: 20  # Increased from 5
MAX_CONCURRENT_WORKERS: 100  # Increased for cloud resources
MAX_CONCURRENT_REQUESTS: 25  # Higher concurrency per worker
REQUESTS_PER_MINUTE: 200  # Higher with multiple API keys

# Memory and Processing
MEMORY_LIMIT_GB: 8
GC_FREQUENCY: 100
ENABLE_MEMORY_MONITORING: true

# Cloud Function Specific
CF_MEMORY_LIMIT: "4096"
CF_CPU_LIMIT: "2"
CF_TIMEOUT: "3600"
CF_CONCURRENCY: "100"

# Worker Specific (for Cloud Run)
NUM_WORKERS: 20
WORKER_MEMORY_LIMIT: "8192"
WORKER_CPU_LIMIT: "4"
WORKER_TIMEOUT: "3600"
```

> **Performance Notes**: These settings are optimized for high-throughput processing in Google Cloud. For detailed explanations and additional optimizations, see [PERFORMANCE_OPTIMIZATION_GUIDE.md](PERFORMANCE_OPTIMIZATION_GUIDE.md).

## 3. Create Dockerfile

Create a `Dockerfile` in the project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \

Notes:
- Option A (Cloud SQL/Memorystore): prefer private IP and connect via the VPC connector.
- Option B (Compute Engine VMs): use the VPC connector to reach internal VM IPs; restrict firewall to connector CIDR.
- Option C (External services): VPC connector not required; ensure outbound egress is allowed and SSL/TLS is enabled (sslmode=require, rediss://).
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p uploads exports logs temp

# Expose port (Cloud Functions will override)
EXPOSE 8080

# Cloud Functions expects the app to listen on 0.0.0.0:8080
CMD ["python", "run_server.py", "--host", "0.0.0.0", "--port", "8080"]
```

## 4. Build and Deploy Cloud Function

### Build the Docker Image
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/image-analyzer .
```

### Deploy Cloud Function (Optimized for Performance)
```bash
gcloud functions deploy image-analyzer \
  --gen2 \
  --runtime python311 \
  --source . \
  --entry-point main \
  --trigger-http \
  --allow-unauthenticated \
  --env-vars-file .env.yaml \
  --memory 4GB \
  --cpu 2 \
  --timeout 3600 \
  --max-instances 50 \
  --min-instances 2 \
  --concurrency 100 \
  --region us-central1 \
  --vpc-connector image-analyzer-connector \
  --egress-settings private-ranges-only \
  --ingress-settings all
```

> **Performance Notes**: 
> - Increased memory from 2GB to 4GB for better processing capacity
> - Added explicit CPU allocation (2 cores) for faster processing
> - Increased timeout from 540s to 3600s for large batch uploads
> - Higher max-instances (50) and min-instances (2) for better scaling
> - Higher concurrency (100) for handling more simultaneous requests
> - See [PERFORMANCE_OPTIMIZATION_GUIDE.md](PERFORMANCE_OPTIMIZATION_GUIDE.md) for more details

## 5. Deploy Background Workers

Since Cloud Functions don't support long-running background processes, deploy workers to Cloud Run:

### Create Worker Dockerfile
Create `Dockerfile.worker`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "run_workers.py"]
```

### Build and Deploy Worker to Cloud Run (Optimized for Performance)
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/image-analyzer-worker .

gcloud run deploy image-analyzer-worker \
  --image gcr.io/YOUR_PROJECT_ID/image-analyzer-worker \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --env-vars-file .env.yaml \
  --memory 8Gi \
  --cpu 4 \
  --max-instances 100 \
  --min-instances 5 \
  --concurrency 50 \
  --timeout 3600s \
  --execution-environment gen2 \
  --cpu-throttling \
  --vpc-connector image-analyzer-connector \
  --vpc-egress private-ranges-only \
  --ingress all
```

> **Performance Notes**: 
> - Increased memory from 2GB to 8Gi for processing large chunks
> - Added 4 CPU cores for parallel processing
> - Higher scaling limits (100 max, 5 min instances)
> - Optimized concurrency (50) for worker processes
> - Gen2 execution environment for better performance
> - See [PERFORMANCE_OPTIMIZATION_GUIDE.md](PERFORMANCE_OPTIMIZATION_GUIDE.md) for details
  --cpu 1 \
  --max-instances 5 \
  --concurrency 1
```

## 6. Configure VPC Access

### Create VPC Connector
```bash
gcloud compute networks vpc-access connectors create image-analyzer-connector \
  --region asia-south2 \
  --range 10.8.0.0/28
```

### Update Cloud Function with VPC
```bash
gcloud functions deploy image-analyzer \
  --vpc-connector image-analyzer-connector \
  --egress-settings all \
  --update-labels
```

### Update Cloud Run with VPC
```bash
gcloud run services update image-analyzer-worker \
  --vpc-connector image-analyzer-connector \
  --egress-settings all
```

## 7. Set Up Cloud Scheduler (Optional)

For periodic cleanup tasks:

```bash
gcloud scheduler jobs create http cleanup-job \
  --schedule "0 */6 * * *" \
  --uri "https://us-central1-YOUR_PROJECT_ID.cloudfunctions.net/image-analyzer/admin/queue/cleanup" \
  --http-method POST \
  --headers "Content-Type=application/json" \
  --message-body '{"max_age_hours": 24}' \
  --oauth-service-account-email YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

## 8. Testing Deployment

### Get Function URL
```bash
gcloud functions describe image-analyzer --region us-central1 --format "value(httpsTrigger.url)"
```

### Test Health Check
```bash
curl https://YOUR_FUNCTION_URL/api/v1/health
```

### Test Batch Upload
```bash
curl -X POST https://YOUR_FUNCTION_URL/api/v1/batches \
  -F "file=@test.csv" \
  -F "batch_name=Test Batch"
```

## 9. Monitoring

### View Logs
```bash
# Cloud Functions logs
gcloud functions logs read image-analyzer --region us-central1

# Cloud Run logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=image-analyzer-worker"
```

### Set Up Alerts
Configure alerts in Cloud Monitoring for:
- Function execution errors
- High latency
- Resource exhaustion

## 10. Cost Optimization

- Use Cloud SQL minimum tier for development
- Set appropriate memory/CPU limits
- Configure auto-scaling limits
- Monitor usage and adjust instance sizes

## Troubleshooting

### Common Issues

1. **VPC Connection Issues**: Ensure VPC connector is properly configured
2. **Database Connection**: Verify Cloud SQL IP allowlist and credentials
3. **Redis Connection**: Check Memorystore instance IP and auth
4. **Timeout Errors**: Increase function timeout or optimize processing
5. **Memory Issues**: Increase memory allocation or optimize code

### Logs Analysis
```bash
# Search for errors
gcloud logging read "severity>=ERROR" --filter "resource.type=cloud_function"

# View specific function logs
gcloud functions logs read image-analyzer --region us-central1 --limit 50
```

## Security Considerations

- Use IAM service accounts with minimal permissions
- Enable VPC for secure database access
- Store secrets in Secret Manager (not environment variables)
- Enable Cloud Armor for DDoS protection
- Regularly rotate API keys and database passwords

---

**Note**: This deployment guide includes basic performance optimizations. For advanced performance tuning and production considerations, see:

- **[PERFORMANCE_OPTIMIZATION_GUIDE.md](PERFORMANCE_OPTIMIZATION_GUIDE.md)** - Comprehensive performance optimization strategies
- Load balancing with Cloud Load Balancer for high availability
- CDN with Cloud CDN for global content delivery
- Backup strategies for Cloud SQL and disaster recovery planning
- Security audits and compliance checks for production workloads
- Monitoring and alerting setup for operational visibility

## Performance Monitoring and Optimization

After deployment, monitor your system's performance using:

1. **Cloud Monitoring**: Track Cloud Function and Cloud Run metrics
2. **Application Performance**: Monitor processing rates and error rates
3. **Database Performance**: Track Cloud SQL connection pools and query performance
4. **Memory Usage**: Monitor memory utilization and optimize as needed

For detailed performance optimization strategies, configuration tuning, and troubleshooting guides, refer to the [Performance Optimization Guide](PERFORMANCE_OPTIMIZATION_GUIDE.md).