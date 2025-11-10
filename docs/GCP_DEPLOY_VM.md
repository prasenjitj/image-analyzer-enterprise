# Step-by-Step Guide: Hosting Enterprise Image Analyzer on GCP VM

This guide provides detailed instructions for deploying the Enterprise Image Analyzer application on a GCP Compute Engine VM instance. Based on your codebase's architecture (Flask web server, background workers, PostgreSQL, Redis, and external API integration), we'll set up a production-ready environment on the specified VM.

## Prerequisites

Before starting, ensure you have:
- **GCP Project Access**: Admin access to project `ops-excellence`
- **External API Endpoint**: Your Gemini AI API endpoint (e.g., `http://34.66.92.16:8000/generate`) configured and accessible
- **Local Machine**: `gcloud` CLI installed and authenticated (`gcloud auth login`)
- **VM Details**:
  - Name: `qwen-vl-vm`
  - Zone: `asia-south2-c`
  - Project: `ops-excellence`
- **Repository**: Codebase cloned locally at [``]( )

## Step 1: Verify VM Access and Setup

### 1.1 Confirm VM Status
```bash
# Check VM details
gcloud compute instances describe qwen-vl-vm \
  --zone=asia-south2-c \
  --project=ops-excellence \
  --format="table(name,status,networkInterfaces[0].accessConfigs[0].natIP)"

# SSH into the VM
gcloud compute ssh qwen-vl-vm \
  --zone=asia-south2-c \
  --project=ops-excellence
```

### 1.2 Update VM and Install Base Dependencies
Once SSH'd into the VM:
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install essential packages
sudo apt install -y python3 python3-pip python3-venv git curl wget unzip

# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Install Redis
sudo apt install -y redis-server

# Verify installations
python3 --version  # Should be 3.8+
psql --version     # PostgreSQL version
redis-server --version  # Redis version
```

## Step 2: Clone and Prepare the Application

### 2.1 Clone Repository
```bash
# Clone the repository (replace with your actual repo URL if different)
git clone https://github.com/your-username/image-analyzer-enterprise.git
cd image-analyzer-enterprise

# If you have local changes, copy them to VM
# scp -r /Users/prasenjitjana/Desktop/image-analyzer-enterprise/* qwen-vl-vm:~/image-analyzer-enterprise/
```

### 2.2 Create Virtual Environment
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip
```

### 2.3 Install Python Dependencies
```bash
# Install all requirements
pip install -r requirements.txt

# Verify key packages
python3 -c "import flask, sqlalchemy, redis, psycopg2; print('Dependencies OK')"
```

## Step 3: Configure Database and Redis

### 3.1 Setup PostgreSQL
```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL shell:
CREATE DATABASE imageprocessing;
CREATE USER prasenjitjana WITH PASSWORD testpass123;
GRANT ALL PRIVILEGES ON DATABASE imageprocessing TO prasenjitjana;
ALTER USER prasenjitjana CREATEDB;
\q
```

### 3.2 Configure Redis
```bash
# Redis should be running by default, verify
sudo systemctl status redis-server
sudo systemctl enable redis-server

# Test Redis connection
redis-cli ping  # Should return PONG
```

## Step 4: Configure Environment Variables

### 4.1 Create Environment File
```bash
# Copy and edit environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

Add/update these key variables in [`.env`](.env ):
```bash
# Database Configuration (preferred: single URL)
# Option A (recommended): single DATABASE_URL
DATABASE_URL=postgresql://prasenjitjana:testpass123@localhost:5432/imageprocessing

# Option B (alternative): individual POSTGRES_* variables
# POSTGRES_HOST=localhost
# POSTGRES_PORT=5432
# POSTGRES_DB=imageprocessing
# POSTGRES_USER=prasenjitjana
# POSTGRES_PASSWORD=testpass123

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# External API / Gemini Configuration
# You can either provide Gemini API keys or point to an external API endpoint
GEMINI_API_KEYS=your_gemini_api_key_here   # comma-separated if multiple
API_ENDPOINT_URL=http://34.66.92.16:8000/generate

# Application Settings
SECRET_KEY=your_very_secure_random_secret_key_here
MAX_UPLOAD_SIZE=104857600
REQUEST_TIMEOUT=60
IMAGE_PROCESSOR_MAX_CONCURRENCY=5

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/enterprise_app.log

# Export / directories
EXPORT_DIR=./exports

# Optional: GCP-specific settings if needed
GOOGLE_CLOUD_PROJECT=ops-excellence
```

### 4.2 Create Required Directories
```bash
# Create necessary directories (added `backups` to match setup.py)
mkdir -p uploads exports logs temp backups

# Set proper permissions
chmod 755 uploads exports logs temp backups

# If you used different paths in your .env (e.g. EXPORT_DIR or LOG_DIR), create them too:
mkdir -p "$(awk -F= '/^EXPORT_DIR/ {print $2}' .env | tr -d ' \n')" || true
mkdir -p "$(awk -F= '/^LOG_DIR/ {print $2}' .env | tr -d ' \n')" || true
```

## Step 5: Initialize Database

### 5.1 Run Database Setup
```bash
# Activate virtual environment
source venv/bin/activate

# Initialize database schema
python setup.py --init-db

# Verify database connection
python setup.py --health-check
```

### 5.2 Test Database Models
```bash
# Quick test of database models
python3 -c "
from src.enterprise_config import config
from src.database_models import db_manager
try:
    session = db_manager.get_session()
    print('Database connection successful')
    session.close()
except Exception as e:
    print(f'Database connection failed: {e}')
"
"
```

## Step 6: Configure Firewall and Networking

### 6.1 Open Required Ports
```bash
# Allow HTTP/HTTPS traffic
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 5001  # Application port

# Enable firewall
sudo ufw --force enable
```

### 6.2 GCP Firewall Rules
From your local machine:
```bash
# Allow traffic to VM on port 5001
gcloud compute firewall-rules create allow-app-5001 \
  --allow tcp:5001 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=http-server \
  --description="Allow application traffic on port 5001" \
  --project=ops-excellence

# Tag your VM with the firewall target
gcloud compute instances add-tags qwen-vl-vm \
  --tags=http-server \
  --zone=us-central1-a \
  --project=ops-excellence
```

## Step 7: Start the Application

### 7.1 Start Background Workers
```bash
# In a screen session or background process
screen -S workers

# Activate environment and start workers
source venv/bin/activate
cd /home/your-username/image-analyzer-enterprise
python server/run_workers.py

# Detach screen: Ctrl+A, D
```

### 7.2 Start Web Server
```bash
# In another screen session
screen -S server

# Activate environment and start server (bind to all interfaces for external access)
source venv/bin/activate
cd /home/your-username/image-analyzer-enterprise
python server/run_server_htttp.py --host 0.0.0.0 --port 5001


# Detach screen: Ctrl+A, D
```

### 7.3 Verify Services are Running
```bash
# Check processes
ps aux | grep python

# Check ports
netstat -tlnp | grep :5001

# Test application
curl http://localhost:5001/api/v1/health
```

## Step 8: Configure Production Settings

### 8.1 Setup Systemd Services (Optional but Recommended)
Create systemd service files for automatic startup:

```bash
# Create service for web server
sudo nano /etc/systemd/system/image-analyzer-server.service
```

Add to `/etc/systemd/system/image-analyzer-server.service`:
```ini
[Unit]
Description=Enterprise Image Analyzer Server
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/image-analyzer-enterprise
Environment=PATH=/home/your-username/image-analyzer-enterprise/venv/bin
ExecStart=/home/your-username/image-analyzer-enterprise/venv/bin/python server/run_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Create service for workers
sudo nano /etc/systemd/system/image-analyzer-workers.service
```

Add to `/etc/systemd/system/image-analyzer-workers.service`:
```ini
[Unit]
Description=Enterprise Image Analyzer Workers
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/image-analyzer-enterprise
Environment=PATH=/home/your-username/image-analyzer-enterprise/venv/bin
ExecStart=/home/your-username/image-analyzer-enterprise/venv/bin/python server/run_workers.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable image-analyzer-server
sudo systemctl enable image-analyzer-workers
sudo systemctl start image-analyzer-server
sudo systemctl start image-analyzer-workers

# Check status
sudo systemctl status image-analyzer-server
sudo systemctl status image-analyzer-workers
```

## Step 9: Test and Monitor

### 9.1 Access the Application
```bash
# Get VM external IP
gcloud compute instances describe qwen-vl-vm \
  --zone=us-central1-a \
  --project=ops-excellence \
  --format="get(networkInterfaces[0].accessConfigs[0].natIP)"

# Access dashboard: http://[VM_EXTERNAL_IP]:5001
```

### 9.2 Test Core Functionality
```bash
# Test health endpoint
curl http://localhost:5001/api/v1/health

# Test with a small CSV upload (create test.csv with a few URLs)
curl -X POST http://localhost:5001/api/v1/batches \
  -F "file=@test.csv" \
  -F "batch_name=Test Batch"

# For external access from your local machine:
# curl -X POST http://[VM_EXTERNAL_IP]:5001/api/v1/batches \
#   -F "file=@test.csv" \
#   -F "batch_name=Test Batch"
```

### 9.3 Monitor Logs
```bash
# Application logs
tail -f logs/enterprise_app.log

# System logs
sudo journalctl -u image-analyzer-server -f
sudo journalctl -u image-analyzer-workers -f
```

## Step 10: Backup and Maintenance

### 10.1 Database Backup
```bash
# Create backup script
sudo nano /usr/local/bin/backup-db.sh
```

Add to `/usr/local/bin/backup-db.sh`:
```bash
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump -U prasenjitjana -h localhost imageprocessing > /home/your-username/backups/db_backup_$DATE.sql
find /home/your-username/backups -name "db_backup_*.sql" -mtime +7 -delete
```

```bash
chmod +x /usr/local/bin/backup-db.sh
sudo crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-db.sh  # Daily at 2 AM
```

### 10.2 Log Rotation
```bash
# Configure logrotate
sudo nano /etc/logrotate.d/image-analyzer
```

Add to `/etc/logrotate.d/image-analyzer`:
```
/home/your-username/image-analyzer-enterprise/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    notifempty
    create 644 your-username your-username
}
```

## Troubleshooting

### Common Issues
1. **Database Connection Failed**: Check PostgreSQL service and credentials
2. **Redis Connection Failed**: Verify Redis is running and accessible
3. **API Timeouts**: Check external API endpoint accessibility and rate limits
4. **Memory Issues**: Monitor with `htop` and adjust worker concurrency
5. **Port Conflicts**: Ensure ports 5001, 5432, 6379 are available

### Health Check
```bash
# Run comprehensive health check
python setup.py --health-check
```

### Logs and Debugging
```bash
# View recent application logs
tail -n 100 logs/enterprise_app.log

# Check systemd service logs
sudo journalctl -u image-analyzer-server --since "1 hour ago"
```

## Security Considerations

1. **Change Default Passwords**: Update PostgreSQL user password
2. **Firewall**: Restrict access to necessary ports only
3. **SSL/TLS**: Consider adding HTTPS with Let's Encrypt
4. **Secrets Management**: Use GCP Secret Manager for sensitive data
5. **Regular Updates**: Keep system packages updated

## Scaling (Future Considerations)

- **Horizontal Scaling**: Add load balancer and multiple VM instances
- **Database Scaling**: Consider read replicas for high read loads
- **Worker Scaling**: Increase worker count or add dedicated worker VMs
- **Monitoring**: Integrate with GCP Monitoring/Cloud Logging

Your application should now be running at `http://[VM_EXTERNAL_IP]:5001`. Follow the QUICK_START.md guide for uploading your first batch of images. If you encounter issues, check the logs and refer to the troubleshooting section above.