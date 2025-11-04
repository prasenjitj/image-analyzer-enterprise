# GCP Free Tier Deployment Guide

## Overview

This guide provides step-by-step instructions to deploy the Enterprise Image Analyzer using Google Cloud Platform's **free tier resources only**. This approach uses:

- **Compute Engine e2-micro instances** (free tier eligible)
- **Self-managed PostgreSQL and Redis**
- **Cloud Functions with free tier limits**
- **Cloud Storage free tier**

**Total estimated cost: $0/month** within free tier limits.

## Prerequisites

- Google Cloud account with free trial credits or billing enabled
- `gcloud` CLI installed and authenticated
- Basic Linux command line knowledge
- Domain name (optional, for custom domains)

## Free Tier Resources Used

- **Compute Engine**: 1 e2-micro instance (PostgreSQL + Redis)
- **Cloud Functions**: 2M invocations/month, 400k GB-seconds/month
- **Cloud Storage**: 5GB storage, 1GB network egress/month
- **VPC**: Free VPC networking

## 1. Initial Setup

### Set Project Variables
```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"  # Free tier eligible region
export ZONE="us-central1-a"
export VPC_NAME="image-analyzer-vpc"
export SUBNET_NAME="image-analyzer-subnet"
```

### Enable Required APIs
```bash
gcloud services enable compute.googleapis.com
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable vpcaccess.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

## 2. Network Setup

### Create VPC Network
```bash
gcloud compute networks create $VPC_NAME --subnet-mode=custom
```

### Create Subnet
```bash
gcloud compute networks subnets create $SUBNET_NAME \
    --network=$VPC_NAME \
    --range=10.10.0.0/24 \
    --region=$REGION
```

### Create Firewall Rules
```bash
# Allow internal communication
gcloud compute firewall-rules create allow-internal \
    --network=$VPC_NAME \
    --allow=tcp,udp,icmp \
    --source-ranges=10.10.0.0/24

# Allow SSH access
gcloud compute firewall-rules create allow-ssh \
    --network=$VPC_NAME \
    --allow=tcp:22 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=ssh

# Allow PostgreSQL from VPC connector
gcloud compute firewall-rules create allow-postgres-serverless \
    --network=$VPC_NAME \
    --allow=tcp:5432 \
    --source-ranges=10.11.0.0/28 \
    --target-tags=database

# Allow Redis from VPC connector  
gcloud compute firewall-rules create allow-redis-serverless \
    --network=$VPC_NAME \
    --allow=tcp:6379 \
    --source-ranges=10.11.0.0/28 \
    --target-tags=cache
```

## 3. Database & Cache Server Setup

### Create e2-micro Instance
```bash
gcloud compute instances create db-cache-server \
    --zone=$ZONE \
    --machine-type=e2-micro \
    --network-interface=subnet=$SUBNET_NAME,no-address \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=10GB \
    --boot-disk-type=pd-standard \
    --tags=database,cache,ssh \
    --metadata=startup-script='#!/bin/bash
apt-get update
apt-get install -y postgresql postgresql-contrib redis-server

# Configure PostgreSQL
sudo -u postgres psql -c "CREATE USER analyzer_user WITH PASSWORD '\''your_secure_password'\'';"
sudo -u postgres psql -c "CREATE DATABASE image_analyzer OWNER analyzer_user;"

# Configure PostgreSQL for remote access
echo "listen_addresses = '\''*'\''" >> /etc/postgresql/14/main/postgresql.conf
echo "host all all 10.10.0.0/24 md5" >> /etc/postgresql/14/main/pg_hba.conf
echo "host all all 10.11.0.0/28 md5" >> /etc/postgresql/14/main/pg_hba.conf

# Configure Redis
sed -i "s/bind 127.0.0.1/bind 0.0.0.0/" /etc/redis/redis.conf
sed -i "s/# requirepass foobared/requirepass your_redis_password/" /etc/redis/redis.conf

# Restart services
systemctl restart postgresql
systemctl restart redis-server
systemctl enable postgresql
systemctl enable redis-server
'
```

### Get Internal IP Address
```bash
export DB_INTERNAL_IP=$(gcloud compute instances describe db-cache-server \
    --zone=$ZONE \
    --format='value(networkInterfaces[0].networkIP)')

echo "Database server internal IP: $DB_INTERNAL_IP"
```

## 4. Cloud Storage Setup

### Create Storage Buckets
```bash
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-image-uploads
gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://${PROJECT_ID}-image-exports

# Set public read access for exports (optional)
gsutil iam ch allUsers:objectViewer gs://${PROJECT_ID}-image-exports
```

## 5. VPC Connector Setup

### Create VPC Access Connector
```bash
gcloud compute networks vpc-access connectors create image-analyzer-connector \
    --region=$REGION \
    --subnet=$SUBNET_NAME \
    --subnet-project=$PROJECT_ID \
    --min-instances=2 \
    --max-instances=3
```

## 6. Environment Configuration

### Create .env.yaml for Cloud Functions
```bash
cat > .env.yaml << EOF
DATABASE_URL: postgresql://analyzer_user:your_secure_password@${DB_INTERNAL_IP}:5432/image_analyzer
REDIS_URL: redis://:your_redis_password@${DB_INTERNAL_IP}:6379/0
GEMINI_API_KEYS: "your_gemini_api_key_1,your_gemini_api_key_2"
SECRET_KEY: "your_super_secret_key_here"
UPLOAD_BUCKET: "gs://${PROJECT_ID}-image-uploads"
EXPORT_BUCKET: "gs://${PROJECT_ID}-image-exports"
MAX_UPLOAD_SIZE: "52428800"
CHUNK_SIZE: "500"
MAX_CONCURRENT_BATCHES: "2"
REQUESTS_PER_MINUTE: "45"
WORKER_COUNT: "10"
LOG_LEVEL: "INFO"
EOF
```

## 7. Application Deployment

### Prepare Source Code
```bash
# Create main.py for Cloud Functions entry point
cat > main.py << 'EOF'
import os
import sys
sys.path.append('src')

from enterprise_app import app

def main(request):
    """Cloud Functions entry point"""
    with app.app_context():
        return app(request.environ, lambda *args: None)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False)
EOF
```

### Deploy Main Application Function
```bash
gcloud functions deploy image-analyzer-app \
    --runtime=python311 \
    --source=. \
    --entry-point=main \
    --trigger-http \
    --allow-unauthenticated \
    --env-vars-file=.env.yaml \
    --memory=512MB \
    --timeout=540s \
    --max-instances=10 \
    --region=$REGION \
    --vpc-connector=image-analyzer-connector \
    --egress-settings=private-ranges-only
```

### Deploy Background Worker Function
```bash
# Create worker entry point
cat > worker_main.py << 'EOF'
import os
import sys
sys.path.append('src')

from background_worker import run_worker_cycle

def worker_main(request):
    """Cloud Functions worker entry point"""
    try:
        result = run_worker_cycle()
        return {'status': 'success', 'processed': result}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}, 500
EOF

gcloud functions deploy image-analyzer-worker \
    --runtime=python311 \
    --source=. \
    --entry-point=worker_main \
    --trigger-http \
    --no-allow-unauthenticated \
    --env-vars-file=.env.yaml \
    --memory=512MB \
    --timeout=540s \
    --max-instances=5 \
    --region=$REGION \
    --vpc-connector=image-analyzer-connector \
    --egress-settings=private-ranges-only
```

## 8. Automated Worker Scheduling

### Create Cloud Scheduler Job
```bash
# Create service account for scheduler
gcloud iam service-accounts create scheduler-sa \
    --display-name="Cloud Scheduler Service Account"

# Grant permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/cloudfunctions.invoker"

# Create scheduler job
gcloud scheduler jobs create http worker-trigger \
    --schedule="*/2 * * * *" \
    --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/image-analyzer-worker" \
    --http-method=POST \
    --oauth-service-account-email="scheduler-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --location=$REGION
```

## 9. Database Initialization

### SSH to Database Server and Initialize
```bash
gcloud compute ssh db-cache-server --zone=$ZONE --command="
sudo -u postgres psql -d image_analyzer -c \"
CREATE TABLE IF NOT EXISTS batch_jobs (
    id SERIAL PRIMARY KEY,
    batch_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    total_images INTEGER DEFAULT 0,
    processed_images INTEGER DEFAULT 0,
    failed_images INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS image_analysis (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER REFERENCES batch_jobs(id),
    image_url VARCHAR(500) NOT NULL,
    image_name VARCHAR(255),
    analysis_result JSONB,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_batch_jobs_status ON batch_jobs(status);
CREATE INDEX idx_image_analysis_batch_id ON image_analysis(batch_id);
CREATE INDEX idx_image_analysis_status ON image_analysis(status);
\"
"
```

## 10. Testing the Deployment

### Get Function URLs
```bash
export MAIN_URL=$(gcloud functions describe image-analyzer-app --region=$REGION --format="value(httpsTrigger.url)")
export WORKER_URL=$(gcloud functions describe image-analyzer-worker --region=$REGION --format="value(httpsTrigger.url)")

echo "Main App URL: $MAIN_URL"
echo "Worker URL: $WORKER_URL"
```

### Test Health Endpoint
```bash
curl -X GET "$MAIN_URL/api/v1/health"
```

### Test Batch Creation
```bash
# Create a test CSV file
echo "image_url,image_name" > test_batch.csv
echo "https://example.com/image1.jpg,test_image_1" >> test_batch.csv
echo "https://example.com/image2.jpg,test_image_2" >> test_batch.csv

# Upload batch
curl -X POST "$MAIN_URL/api/v1/batches" \
    -F "file=@test_batch.csv" \
    -F "batch_name=Free Tier Test Batch"
```

## 11. Monitoring and Optimization

### View Logs
```bash
# Application logs
gcloud functions logs read image-analyzer-app --region=$REGION --limit=50

# Worker logs  
gcloud functions logs read image-analyzer-worker --region=$REGION --limit=50

# Database server logs
gcloud compute ssh db-cache-server --zone=$ZONE --command="sudo tail -f /var/log/postgresql/postgresql-14-main.log"
```

### Monitor Resource Usage
```bash
# Check function metrics
gcloud functions describe image-analyzer-app --region=$REGION

# Check VM usage
gcloud compute ssh db-cache-server --zone=$ZONE --command="htop"
```

### Free Tier Usage Monitoring
```bash
# Check Cloud Functions usage
gcloud logging read "resource.type=cloud_function" --format="table(timestamp,resource.labels.function_name)" --limit=100

# Check storage usage
gsutil du -s gs://${PROJECT_ID}-image-uploads
gsutil du -s gs://${PROJECT_ID}-image-exports
```

## 12. Scaling Within Free Tier

### Optimize Function Memory
```bash
# Reduce memory for lower usage (saves on GB-seconds)
gcloud functions deploy image-analyzer-app \
    --memory=256MB \
    --update-env-vars WORKER_COUNT=5
```

### Implement Request Batching
- Process multiple images per function invocation
- Use Cloud Tasks for queuing when approaching limits
- Implement exponential backoff for API calls

### Database Optimization
```bash
# Connect to database and optimize
gcloud compute ssh db-cache-server --zone=$ZONE --command="
sudo -u postgres psql -d image_analyzer -c \"
-- Add indices for better performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_batch_created_at ON batch_jobs(created_at);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_analysis_processed_at ON image_analysis(processed_at);

-- Set up automatic cleanup
CREATE OR REPLACE FUNCTION cleanup_old_data() RETURNS void AS \$\$
BEGIN
    DELETE FROM image_analysis WHERE created_at < NOW() - INTERVAL '30 days';
    DELETE FROM batch_jobs WHERE created_at < NOW() - INTERVAL '30 days';
END;
\$\$ LANGUAGE plpgsql;
\"
"
```

## 13. Backup Strategy

### Automated Database Backup
```bash
# Create backup script
gcloud compute ssh db-cache-server --zone=$ZONE --command="
cat > /home/\$USER/backup_db.sh << 'BACKUP_EOF'
#!/bin/bash
BACKUP_DIR=\"/home/\$USER/backups\"
mkdir -p \$BACKUP_DIR
DATE=\$(date +%Y%m%d_%H%M%S)
sudo -u postgres pg_dump image_analyzer > \$BACKUP_DIR/backup_\$DATE.sql
# Keep only last 7 days of backups
find \$BACKUP_DIR -name 'backup_*.sql' -mtime +7 -delete
BACKUP_EOF

chmod +x /home/\$USER/backup_db.sh

# Add to crontab for daily backups
(crontab -l 2>/dev/null; echo '0 2 * * * /home/\$USER/backup_db.sh') | crontab -
"
```

## 14. Security Hardening

### Secure Database Access
```bash
# Update firewall to be more restrictive
gcloud compute firewall-rules update allow-postgres-serverless \
    --source-ranges=10.11.0.0/28  # Only VPC connector range

gcloud compute firewall-rules update allow-redis-serverless \
    --source-ranges=10.11.0.0/28  # Only VPC connector range
```

### Environment Variables Security
```bash
# Use Secret Manager for sensitive data (within free tier limits)
echo "your_secure_password" | gcloud secrets create db-password --data-file=-
echo "your_redis_password" | gcloud secrets create redis-password --data-file=-
echo "your_super_secret_key" | gcloud secrets create app-secret-key --data-file=-

# Update .env.yaml to reference secrets
cat > .env.yaml << EOF
DATABASE_URL: postgresql://analyzer_user:\${SECRET_DB_PASSWORD}@${DB_INTERNAL_IP}:5432/image_analyzer
REDIS_URL: redis://:\${SECRET_REDIS_PASSWORD}@${DB_INTERNAL_IP}:6379/0
SECRET_KEY: \${SECRET_APP_KEY}
# ... other vars
EOF
```

## 15. Troubleshooting

### Common Issues

**Function Timeout**
```bash
# Increase timeout (max 540s for HTTP functions)
gcloud functions deploy image-analyzer-app --timeout=540s
```

**Memory Issues**
```bash
# Monitor memory usage
gcloud functions logs read image-analyzer-app --region=$REGION | grep "Memory"
```

**Database Connection Issues**
```bash
# Test connection from function
gcloud compute ssh db-cache-server --zone=$ZONE --command="
sudo -u postgres psql -d image_analyzer -c 'SELECT NOW();'
"
```

**VPC Connector Issues**
```bash
# Check connector status
gcloud compute networks vpc-access connectors describe image-analyzer-connector --region=$REGION
```

### Performance Monitoring
```bash
# Create monitoring dashboard script
cat > monitor.sh << 'EOF'
#!/bin/bash
echo "=== Function Metrics ==="
gcloud functions describe image-analyzer-app --region=$REGION --format="value(status)"

echo "=== Database Server Status ==="
gcloud compute instances describe db-cache-server --zone=$ZONE --format="value(status)"

echo "=== Storage Usage ==="
gsutil du -sh gs://${PROJECT_ID}-image-uploads
gsutil du -sh gs://${PROJECT_ID}-image-exports

echo "=== Recent Errors ==="
gcloud logging read "severity>=ERROR AND resource.type=cloud_function" --limit=5
EOF

chmod +x monitor.sh
```

## 16. Cost Management

### Set Up Billing Alerts
```bash
# Enable billing API
gcloud services enable billingbudgets.googleapis.com

# Note: Billing budgets require billing account admin permissions
# Set up through Cloud Console: Billing > Budgets & Alerts
```

### Free Tier Limits Monitoring
- **Cloud Functions**: 2M invocations/month, 400k GB-seconds
- **Cloud Storage**: 5GB storage, 1GB egress/month  
- **Compute Engine**: 1 e2-micro instance
- **VPC**: Unlimited internal traffic

### Optimization Tips
1. **Batch Processing**: Process multiple images per function call
2. **Caching**: Use Redis to cache frequent API responses
3. **Compression**: Compress images before processing
4. **Cleanup**: Regularly remove old data and files
5. **Monitoring**: Track usage to avoid exceeding free tier

---

**This guide provides a complete free-tier deployment that can handle moderate workloads while staying within Google Cloud's always-free tier limits.**