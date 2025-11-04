# Enterprise Image Analyzer - Performance Optimization Guide

## Table of Contents
1. [Overview](#overview)
2. [Cloud Function Performance Optimization](#cloud-function-performance-optimization)
3. [Cloud Run Performance Optimization](#cloud-run-performance-optimization)
4. [Database Performance Optimization](#database-performance-optimization)
5. [Redis Performance Optimization](#redis-performance-optimization)
6. [Application-Level Performance Tuning](#application-level-performance-tuning)
7. [Monitoring and Scaling Strategies](#monitoring-and-scaling-strategies)
8. [Environment-Specific Configurations](#environment-specific-configurations)
9. [Performance Benchmarks and Testing](#performance-benchmarks-and-testing)
10. [Troubleshooting Performance Issues](#troubleshooting-performance-issues)

## Overview

This comprehensive guide consolidates all performance optimization strategies for the Enterprise Image Analyzer system. It covers cloud infrastructure optimization, application-level tuning, and monitoring strategies to achieve maximum processing throughput for large-scale image analysis workloads.

### Performance Goals
- **Throughput**: Process 15M+ URLs efficiently
- **Latency**: Minimize response times for API calls
- **Scalability**: Auto-scale based on workload demands
- **Cost Efficiency**: Optimize resource usage vs performance
- **Reliability**: Maintain performance under high load

## Cloud Function Performance Optimization

### Current Configuration Analysis
The current Cloud Function deployment has several areas for improvement:

```bash
# Current deployment command in build_and_deploy_server.sh
gcloud functions deploy image-analyzer \
    --gen2 \
    --runtime=python39 \
    --region="$REGION" \
    --source=. \
    --entry-point=app \
    --trigger-http \
    --allow-unauthenticated \
    --env-vars-file=.env.yaml \
    --memory=2GB \
    --timeout=540s \
    --max-instances=10 \
    --vpc-connector="$VPC_CONNECTOR" \
    --egress-settings=private-ranges-only
```

### Recommended Optimizations

#### 1. Resource Allocation Improvements
```bash
# Optimized deployment command
gcloud functions deploy image-analyzer \
    --gen2 \
    --runtime=python311 \                    # Latest Python for performance
    --region="$REGION" \
    --source=. \
    --entry-point=app \
    --trigger-http \
    --allow-unauthenticated \
    --env-vars-file=.env.yaml \
    --memory=4GB \                           # Increased from 2GB
    --cpu=2 \                                # NEW: Explicit CPU allocation
    --timeout=3600s \                        # Increased from 540s for large batches
    --max-instances=50 \                     # Increased from 10
    --min-instances=2 \                      # NEW: Keep warm instances
    --concurrency=100 \                      # NEW: Higher concurrency
    --vpc-connector="$VPC_CONNECTOR" \
    --egress-settings=private-ranges-only \
    --ingress-settings=all \                 # NEW: Allow all ingress
    --execution-environment=gen2            # Ensure Gen2 for better performance
```

#### 2. Environment Variables for Cloud Functions
Add to `.env.yaml`:
```yaml
# Cloud Function Specific Optimizations
CF_MEMORY_LIMIT: "4096"
CF_CPU_LIMIT: "2"
CF_TIMEOUT: "3600"
CF_CONCURRENCY: "100"

# Application Performance Tuning
MAX_CONCURRENT_WORKERS: 100
MAX_CONCURRENT_BATCHES: 20
CHUNK_SIZE: 2000
MAX_CONCURRENT_REQUESTS: 25

# Database Connection Optimization for Cloud Functions
DATABASE_POOL_SIZE: 100
DATABASE_MAX_OVERFLOW: 200
DATABASE_POOL_RECYCLE: 1800
DATABASE_POOL_PRE_PING: true

# Redis Optimization for Cloud Functions
REDIS_MAX_CONNECTIONS: 500
REDIS_SOCKET_TIMEOUT: 10
REDIS_SOCKET_CONNECT_TIMEOUT: 5
```

#### 3. Cold Start Optimization
Add to your Dockerfile:
```dockerfile
FROM python:3.11-slim

# Optimize for faster cold starts
WORKDIR /app

# Install system dependencies first (cached layer)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy and install requirements first (cached if unchanged)
COPY requirements.txt .
RUN pip install --no-cache-dir --compile -r requirements.txt

# Pre-compile Python files
COPY . .
RUN python -m compileall .

# Pre-create directories
RUN mkdir -p uploads exports logs temp

# Optimize for Cloud Functions
ENV PYTHONPATH=/app
ENV PYTHONOPTIMIZE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "server/run_server_cloud.py"]
```

## Cloud Run Performance Optimization

### Current Configuration Analysis
The current Cloud Run worker deployment needs significant optimization:

```bash
# Current deployment in build_and_deploy_worker.sh
gcloud run deploy image-analyzer-worker \
    --image="gcr.io/$PROJECT_ID/image-analyzer-worker:latest" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=2Gi \
    --cpu=2 \
    --env-vars-file=.env.yaml \
    --max-instances=5 \
    --concurrency=10 \
    --vpc-connector="$VPC_CONNECTOR"
```

### Recommended Optimizations

#### 1. Enhanced Cloud Run Configuration
```bash
# Optimized Cloud Run deployment
gcloud run deploy image-analyzer-worker \
    --image="gcr.io/$PROJECT_ID/image-analyzer-worker:latest" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=8Gi \                           # Increased from 2Gi
    --cpu=4 \                                # Increased from 2
    --env-vars-file=.env.yaml \
    --max-instances=100 \                    # Increased from 5
    --min-instances=5 \                      # NEW: Keep warm instances
    --concurrency=50 \                       # Increased from 10
    --cpu-throttling \                       # NEW: Enable CPU throttling
    --execution-environment=gen2 \           # Use Gen2 for better performance
    --port=8080 \
    --timeout=3600s \                        # NEW: Explicit timeout
    --vpc-connector="$VPC_CONNECTOR" \
    --vpc-egress=private-ranges-only \
    --ingress=all \
    --service-account="$SERVICE_ACCOUNT" \   # NEW: Dedicated service account
    --labels="app=image-analyzer,component=worker,environment=production"
```

#### 2. Auto-scaling Configuration
```bash
# Add auto-scaling annotations
gcloud run services update image-analyzer-worker \
    --region="$REGION" \
    --update-annotations="autoscaling.knative.dev/minScale=5" \
    --update-annotations="autoscaling.knative.dev/maxScale=100" \
    --update-annotations="run.googleapis.com/cpu-throttling=true" \
    --update-annotations="run.googleapis.com/execution-environment=gen2"
```

#### 3. Worker-Specific Environment Variables
Add to `.env.yaml`:
```yaml
# Cloud Run Worker Specific
NUM_WORKERS: 20                             # Dynamic based on CPU cores
WORKER_MEMORY_LIMIT: "8192"
WORKER_CPU_LIMIT: "4"
WORKER_TIMEOUT: "3600"

# Processing Optimization
CHUNK_PROCESSING_TIMEOUT: 3600
MAX_CONCURRENT_CHUNKS: 10
WORKER_BATCH_SIZE: 500
WORKER_QUEUE_PREFETCH: 50

# Memory Management
MEMORY_LIMIT_GB: 8
GC_FREQUENCY: 100
ENABLE_MEMORY_MONITORING: true
```

#### 4. Optimized Worker Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Multi-stage build for smaller image
# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Optimize pip installation
COPY requirements.txt .
RUN pip install --no-cache-dir --compile \
    --user \
    -r requirements.txt

# Copy application
COPY . .

# Optimize Python execution
ENV PYTHONPATH=/app
ENV PYTHONOPTIMIZE=2
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Pre-compile Python files
RUN python -m compileall -b .

# Create necessary directories
RUN mkdir -p uploads exports logs temp

# Use the Cloud Run HTTP wrapper
CMD ["python", "server/run_worker_http.py"]
```

## Database Performance Optimization

### PostgreSQL Configuration

#### 1. Cloud SQL Optimization
```bash
# Create high-performance Cloud SQL instance
gcloud sql instances create image-analyzer-db \
    --database-version=POSTGRES_15 \
    --tier=db-custom-4-16384 \              # 4 vCPUs, 16GB RAM
    --region=us-central1 \
    --storage-type=SSD \
    --storage-size=500GB \
    --storage-auto-increase \
    --storage-auto-increase-limit=1000GB \
    --availability-type=REGIONAL \           # High availability
    --backup-start-time=03:00 \
    --maintenance-window-day=SUN \
    --maintenance-window-hour=04 \
    --deletion-protection \
    --database-flags=shared_preload_libraries=pg_stat_statements \
    --database-flags=max_connections=1000 \
    --database-flags=shared_buffers=4096MB \
    --database-flags=effective_cache_size=12GB \
    --database-flags=work_mem=32MB \
    --database-flags=maintenance_work_mem=512MB \
    --database-flags=checkpoint_completion_target=0.9 \
    --database-flags=wal_buffers=32MB \
    --database-flags=random_page_cost=1.1
```

#### 2. Database Schema Optimization
```sql
-- Create optimized indexes for common queries
CREATE INDEX CONCURRENTLY idx_batches_status_created 
ON processing_batches(status, created_at);

CREATE INDEX CONCURRENTLY idx_chunks_batch_status 
ON processing_chunks(batch_id, status);

CREATE INDEX CONCURRENTLY idx_results_batch_success 
ON url_analysis_results(batch_id, success);

CREATE INDEX CONCURRENTLY idx_results_created_batch 
ON url_analysis_results(created_at DESC, batch_id);

-- Partitioning for large tables
CREATE TABLE url_analysis_results_y2024m11 
PARTITION OF url_analysis_results 
FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');

-- Optimize statistics
ALTER TABLE processing_batches SET (autovacuum_vacuum_scale_factor = 0.1);
ALTER TABLE url_analysis_results SET (autovacuum_vacuum_scale_factor = 0.05);

-- Create partial indexes for common filters
CREATE INDEX CONCURRENTLY idx_results_failed 
ON url_analysis_results(batch_id, created_at) 
WHERE success = false;

CREATE INDEX CONCURRENTLY idx_batches_active 
ON processing_batches(created_at, batch_id) 
WHERE status IN ('PENDING', 'PROCESSING', 'QUEUED');
```

#### 3. Connection Pool Optimization
Update `enterprise_config.py`:
```python
# Enhanced database configuration
database_pool_size: int = Field(200, env="DATABASE_POOL_SIZE")
database_max_overflow: int = Field(300, env="DATABASE_MAX_OVERFLOW")
database_pool_timeout: int = Field(30, env="DATABASE_POOL_TIMEOUT")
database_pool_recycle: int = Field(1800, env="DATABASE_POOL_RECYCLE")
database_pool_pre_ping: bool = Field(True, env="DATABASE_POOL_PRE_PING")
database_echo: bool = Field(False, env="DATABASE_ECHO")

def get_database_config(self) -> dict:
    """Get optimized database configuration for SQLAlchemy"""
    return {
        'url': self.database_url,
        'pool_size': self.database_pool_size,
        'max_overflow': self.database_max_overflow,
        'pool_timeout': self.database_pool_timeout,
        'pool_recycle': self.database_pool_recycle,
        'pool_pre_ping': self.database_pool_pre_ping,
        'echo': self.database_echo,
        'pool_reset_on_return': 'commit',
        'connect_args': {
            'application_name': 'image_analyzer',
            'connect_timeout': 10,
            'options': '-c statement_timeout=300000'  # 5 minute query timeout
        }
    }
```

## Redis Performance Optimization

### Cloud Memorystore Configuration
```bash
# Create high-performance Redis instance
gcloud redis instances create image-analyzer-redis \
    --size=5 \                               # 5GB instance
    --region=us-central1 \
    --redis-version=redis_6_x \
    --tier=standard \                        # High availability
    --redis-config maxmemory-policy=allkeys-lru \
    --redis-config notify-keyspace-events=Ex \
    --redis-config timeout=300 \
    --redis-config tcp-keepalive=60 \
    --display-name="Image Analyzer Redis" \
    --labels=app=image-analyzer,component=cache
```

### Redis Configuration Optimization
Update `enterprise_config.py`:
```python
# Enhanced Redis configuration
redis_max_connections: int = Field(1000, env="REDIS_MAX_CONNECTIONS")
redis_socket_timeout: int = Field(10, env="REDIS_SOCKET_TIMEOUT")
redis_socket_connect_timeout: int = Field(5, env="REDIS_SOCKET_CONNECT_TIMEOUT")
redis_health_check_interval: int = Field(30, env="REDIS_HEALTH_CHECK_INTERVAL")
redis_retry_on_timeout: bool = Field(True, env="REDIS_RETRY_ON_TIMEOUT")
redis_connection_pool_kwargs: dict = Field(default_factory=dict)

def get_redis_config(self) -> dict:
    """Get optimized Redis configuration"""
    config = {
        'url': self.redis_url,
        'db': self.redis_db,
        'socket_timeout': self.redis_socket_timeout,
        'socket_connect_timeout': self.redis_socket_connect_timeout,
        'health_check_interval': self.redis_health_check_interval,
        'retry_on_timeout': self.redis_retry_on_timeout,
        'decode_responses': True,
        'max_connections': self.redis_max_connections
    }
    
    if self.redis_password:
        config['password'] = self.redis_password
    
    return config
```

### Job Queue Optimization
Update `job_queue.py`:
```python
class OptimizedJobQueue:
    def __init__(self):
        self.redis_client = redis.ConnectionPool(
            max_connections=1000,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        # Optimize job processing
        self.batch_size = 100  # Process jobs in batches
        self.prefetch_count = 50  # Pre-fetch jobs
        self.visibility_timeout = 300  # 5 minute visibility
        
    async def process_jobs_batch(self, batch_size: int = 100):
        """Process multiple jobs in parallel"""
        jobs = await self.get_jobs_batch(batch_size)
        tasks = [self.process_job(job) for job in jobs]
        await asyncio.gather(*tasks, return_exceptions=True)
```

## Application-Level Performance Tuning

### 1. Processing Pipeline Optimization

#### Enhanced Chunk Processing
Update `background_worker.py`:
```python
class OptimizedChunkProcessor:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.processor = ImageProcessor(
            api_keys=config.api_keys_list,
            max_workers=config.max_concurrent_requests,
            image_max_size=config.image_max_size,
            session_pool_size=100,  # Connection pool
            timeout_config={
                'connect': 10,
                'read': 30,
                'total': 60
            }
        )
        
        # Memory optimization
        self.memory_monitor = MemoryMonitor(
            max_memory_gb=config.memory_limit_gb,
            gc_frequency=config.gc_frequency
        )
        
        # Batch processing optimization
        self.batch_size = min(500, config.chunk_size // 4)
        self.concurrent_batches = min(10, config.max_concurrent_chunks)
        
    async def process_chunk_optimized(self, batch_id: str, chunk_id: str, urls: List[str]):
        """Optimized chunk processing with memory management"""
        chunk_start_time = time.time()
        
        # Memory check before processing
        self.memory_monitor.check_memory_usage()
        
        # Process in optimized sub-batches
        results = []
        for i in range(0, len(urls), self.batch_size):
            sub_batch = urls[i:i + self.batch_size]
            
            # Parallel processing with memory monitoring
            batch_results = await self._process_sub_batch_parallel(sub_batch)
            results.extend(batch_results)
            
            # Update progress and memory
            self._update_progress(chunk_id, len(results), len(urls))
            self.memory_monitor.cleanup_if_needed()
            
        return results
    
    async def _process_sub_batch_parallel(self, urls: List[str]) -> List[Any]:
        """Process sub-batch with parallel semaphore control"""
        semaphore = asyncio.Semaphore(self.concurrent_batches)
        
        async def process_with_semaphore(url):
            async with semaphore:
                return await self.processor.process_single_url(url)
        
        tasks = [process_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

#### Memory Management
```python
class MemoryMonitor:
    def __init__(self, max_memory_gb: int, gc_frequency: int):
        self.max_memory_gb = max_memory_gb
        self.gc_frequency = gc_frequency
        self.process_count = 0
        
    def check_memory_usage(self):
        """Monitor and manage memory usage"""
        import psutil
        import gc
        
        process = psutil.Process()
        memory_gb = process.memory_info().rss / (1024 ** 3)
        
        if memory_gb > self.max_memory_gb * 0.8:  # 80% threshold
            logger.warning(f"High memory usage: {memory_gb:.2f}GB")
            self.cleanup_if_needed()
            
        self.process_count += 1
        
    def cleanup_if_needed(self):
        """Force garbage collection and cleanup"""
        import gc
        
        if self.process_count % self.gc_frequency == 0:
            collected = gc.collect()
            logger.debug(f"Garbage collection freed {collected} objects")
```

### 2. API Rate Limiting Optimization

#### Dynamic Rate Limiting
```python
class DynamicRateLimiter:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.rate_limits = {}
        self.current_usage = {}
        
        # Initialize per-key limits
        for key in api_keys:
            self.rate_limits[key] = {
                'rpm': 60,  # Start conservative
                'window': 60,
                'burst': 10
            }
    
    async def adaptive_rate_limit(self, api_key: str):
        """Adaptively adjust rate limits based on success/failure rates"""
        current_time = time.time()
        
        # Check if we can increase rate limit
        if self._get_success_rate(api_key) > 0.95:
            self.rate_limits[api_key]['rpm'] = min(
                self.rate_limits[api_key]['rpm'] * 1.1, 
                100  # Max RPM per key
            )
        elif self._get_success_rate(api_key) < 0.8:
            self.rate_limits[api_key]['rpm'] = max(
                self.rate_limits[api_key]['rpm'] * 0.9,
                30  # Min RPM per key
            )
            
        await self._wait_if_needed(api_key)
```

### 3. Caching Optimization

#### Multi-Level Caching
```python
class OptimizedCache:
    def __init__(self, db_path: str, redis_client):
        self.local_cache = {}  # In-memory L1 cache
        self.sqlite_cache = SQLiteCache(db_path)  # L2 cache
        self.redis_cache = redis_client  # L3 distributed cache
        
        # Cache configuration
        self.l1_max_size = 10000
        self.l1_ttl = 3600  # 1 hour
        self.l2_ttl = 86400  # 24 hours
        self.l3_ttl = 604800  # 7 days
        
    async def get_analysis(self, url: str) -> Optional[dict]:
        """Multi-level cache lookup"""
        # L1 (Memory) - fastest
        if url in self.local_cache:
            if time.time() - self.local_cache[url]['timestamp'] < self.l1_ttl:
                return self.local_cache[url]['data']
            else:
                del self.local_cache[url]
        
        # L2 (SQLite) - fast local disk
        result = await self.sqlite_cache.get(url)
        if result:
            self._update_l1_cache(url, result)
            return result
            
        # L3 (Redis) - distributed cache
        result = await self.redis_cache.get(f"analysis:{url}")
        if result:
            result = json.loads(result)
            self._update_l1_cache(url, result)
            await self.sqlite_cache.set(url, result, self.l2_ttl)
            return result
            
        return None
    
    async def set_analysis(self, url: str, analysis: dict):
        """Multi-level cache storage"""
        # Store in all levels
        self._update_l1_cache(url, analysis)
        await self.sqlite_cache.set(url, analysis, self.l2_ttl)
        await self.redis_cache.setex(
            f"analysis:{url}", 
            self.l3_ttl, 
            json.dumps(analysis)
        )
```

## Monitoring and Scaling Strategies

### 1. Performance Monitoring

#### Application Metrics
```python
import time
from dataclasses import dataclass
from typing import Dict, List
import psutil

@dataclass
class PerformanceMetrics:
    timestamp: float
    cpu_percent: float
    memory_mb: float
    active_workers: int
    queue_size: int
    processing_rate: float  # URLs per minute
    error_rate: float
    avg_response_time: float

class PerformanceMonitor:
    def __init__(self):
        self.metrics_history: List[PerformanceMetrics] = []
        self.start_time = time.time()
        self.processed_count = 0
        self.error_count = 0
        
    def record_metrics(self):
        """Record current performance metrics"""
        process = psutil.Process()
        
        metrics = PerformanceMetrics(
            timestamp=time.time(),
            cpu_percent=process.cpu_percent(),
            memory_mb=process.memory_info().rss / (1024 * 1024),
            active_workers=self._get_active_workers(),
            queue_size=self._get_queue_size(),
            processing_rate=self._calculate_processing_rate(),
            error_rate=self._calculate_error_rate(),
            avg_response_time=self._calculate_avg_response_time()
        )
        
        self.metrics_history.append(metrics)
        
        # Keep only last hour of metrics
        cutoff_time = time.time() - 3600
        self.metrics_history = [
            m for m in self.metrics_history 
            if m.timestamp > cutoff_time
        ]
        
        return metrics
    
    def should_scale_up(self) -> bool:
        """Determine if we should scale up resources"""
        if len(self.metrics_history) < 5:
            return False
            
        recent_metrics = self.metrics_history[-5:]
        
        # Scale up if:
        # 1. CPU usage consistently high (>80%)
        # 2. Queue size growing
        # 3. Processing rate declining
        
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        queue_growing = recent_metrics[-1].queue_size > recent_metrics[0].queue_size
        
        return avg_cpu > 80 and queue_growing
    
    def should_scale_down(self) -> bool:
        """Determine if we should scale down resources"""
        if len(self.metrics_history) < 10:
            return False
            
        recent_metrics = self.metrics_history[-10:]
        
        # Scale down if:
        # 1. CPU usage consistently low (<30%)
        # 2. Queue size small
        # 3. Low error rate
        
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_queue = sum(m.queue_size for m in recent_metrics) / len(recent_metrics)
        avg_error_rate = sum(m.error_rate for m in recent_metrics) / len(recent_metrics)
        
        return avg_cpu < 30 and avg_queue < 100 and avg_error_rate < 0.05
```

#### Cloud Monitoring Integration
```python
from google.cloud import monitoring_v3
import json

class CloudMonitoringIntegration:
    def __init__(self, project_id: str):
        self.client = monitoring_v3.MetricServiceClient()
        self.project_name = f"projects/{project_id}"
        
    def send_custom_metrics(self, metrics: PerformanceMetrics):
        """Send custom metrics to Cloud Monitoring"""
        series = monitoring_v3.TimeSeries()
        series.metric.type = "custom.googleapis.com/image_analyzer/processing_rate"
        series.resource.type = "cloud_function"
        
        point = monitoring_v3.Point()
        point.value.double_value = metrics.processing_rate
        point.interval.end_time.seconds = int(metrics.timestamp)
        series.points = [point]
        
        self.client.create_time_series(
            name=self.project_name,
            time_series=[series]
        )
```

### 2. Auto-scaling Configuration

#### Horizontal Pod Autoscaler (for Cloud Run)
```yaml
# cloud-run-autoscaler.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: image-analyzer-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: run.googleapis.com/v1
    kind: Service
    name: image-analyzer-worker
  minReplicas: 5
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
```

## Environment-Specific Configurations

### Development Environment
```bash
# .env.development
# Optimized for development speed and debugging

# Reduced resource usage for local development
MAX_CONCURRENT_WORKERS=4
MAX_CONCURRENT_BATCHES=2
CHUNK_SIZE=100
MAX_CONCURRENT_REQUESTS=5

# Fast feedback for development
REQUEST_TIMEOUT=15
RETRY_ATTEMPTS=2
PROGRESS_UPDATE_INTERVAL=5

# Database settings for local PostgreSQL
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

# Redis settings for local Redis
REDIS_MAX_CONNECTIONS=50

# Debug settings
ENABLE_DEBUG_LOGGING=true
DEVELOPMENT_MODE=true
DATABASE_ECHO=false  # Set to true for SQL debugging
```

### Staging Environment
```bash
# .env.staging
# Moderate resources for testing at scale

# Moderate resource usage
MAX_CONCURRENT_WORKERS=20
MAX_CONCURRENT_BATCHES=5
CHUNK_SIZE=1000
MAX_CONCURRENT_REQUESTS=15

# Production-like timeouts
REQUEST_TIMEOUT=30
RETRY_ATTEMPTS=3
PROGRESS_UPDATE_INTERVAL=10

# Cloud SQL settings
DATABASE_POOL_SIZE=50
DATABASE_MAX_OVERFLOW=100

# Cloud Redis settings
REDIS_MAX_CONNECTIONS=200

# Monitoring enabled
ENABLE_MONITORING=true
ENABLE_DEBUG_LOGGING=false
```

### Production Environment
```bash
# .env.production
# Maximum performance configuration

# High-performance settings
MAX_CONCURRENT_WORKERS=100
MAX_CONCURRENT_BATCHES=20
CHUNK_SIZE=2000
MAX_CONCURRENT_REQUESTS=25

# Production timeouts
REQUEST_TIMEOUT=30
RETRY_ATTEMPTS=3
PROGRESS_UPDATE_INTERVAL=30

# High-performance database
DATABASE_POOL_SIZE=200
DATABASE_MAX_OVERFLOW=300
DATABASE_POOL_TIMEOUT=30
DATABASE_POOL_RECYCLE=1800

# High-performance Redis
REDIS_MAX_CONNECTIONS=1000
REDIS_SOCKET_TIMEOUT=10

# Production monitoring
ENABLE_MONITORING=true
ENABLE_DEBUG_LOGGING=false
MONITORING_PORT=8080

# Security and reliability
DEVELOPMENT_MODE=false
DATABASE_ECHO=false
```

## Performance Benchmarks and Testing

### 1. Load Testing Configuration

#### Artillery Load Test
```yaml
# artillery-load-test.yml
config:
  target: "https://your-cloud-function-url"
  phases:
    - duration: 300  # 5 minutes
      arrivalRate: 1
      name: "Warm up"
    - duration: 600  # 10 minutes
      arrivalRate: 10
      name: "Ramp up load"
    - duration: 1200  # 20 minutes
      arrivalRate: 50
      name: "Sustained high load"
    - duration: 300  # 5 minutes
      arrivalRate: 1
      name: "Cool down"
  defaults:
    headers:
      Content-Type: "application/json"

scenarios:
  - name: "Batch Upload and Processing"
    weight: 100
    flow:
      - post:
          url: "/upload"
          formData:
            file: "@test_batch_1000.csv"
            batch_name: "Load Test Batch {{ $randomString() }}"
            auto_start: "true"
      - think: 5
      - get:
          url: "/api/v1/system/stats"
          capture:
            - json: "$.data.queue_stats.pending"
              as: "pendingJobs"
      - think: 10
```

#### Performance Test Script
```python
# performance_test.py
import asyncio
import aiohttp
import time
from typing import List, Dict
import json

class PerformanceTester:
    def __init__(self, base_url: str, concurrent_requests: int = 10):
        self.base_url = base_url
        self.concurrent_requests = concurrent_requests
        self.results = []
        
    async def run_performance_test(self, test_duration: int = 300):
        """Run performance test for specified duration"""
        start_time = time.time()
        end_time = start_time + test_duration
        
        async with aiohttp.ClientSession() as session:
            while time.time() < end_time:
                # Create batch of concurrent requests
                tasks = []
                for _ in range(self.concurrent_requests):
                    task = self.make_test_request(session)
                    tasks.append(task)
                
                # Execute requests concurrently
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Record results
                for result in results:
                    if not isinstance(result, Exception):
                        self.results.append(result)
                
                # Brief pause between batches
                await asyncio.sleep(1)
        
        return self.analyze_results()
    
    async def make_test_request(self, session: aiohttp.ClientSession):
        """Make a test API request"""
        start_time = time.time()
        
        try:
            async with session.get(f"{self.base_url}/api/v1/system/stats") as response:
                end_time = time.time()
                response_data = await response.json()
                
                return {
                    'timestamp': start_time,
                    'response_time': end_time - start_time,
                    'status_code': response.status,
                    'success': response.status == 200,
                    'queue_size': response_data.get('data', {}).get('queue_stats', {}).get('pending', 0)
                }
        except Exception as e:
            return {
                'timestamp': start_time,
                'response_time': time.time() - start_time,
                'status_code': 0,
                'success': False,
                'error': str(e)
            }
    
    def analyze_results(self) -> Dict:
        """Analyze performance test results"""
        if not self.results:
            return {'error': 'No results to analyze'}
        
        successful_requests = [r for r in self.results if r['success']]
        failed_requests = [r for r in self.results if not r['success']]
        
        response_times = [r['response_time'] for r in successful_requests]
        
        analysis = {
            'total_requests': len(self.results),
            'successful_requests': len(successful_requests),
            'failed_requests': len(failed_requests),
            'success_rate': len(successful_requests) / len(self.results) * 100,
            'avg_response_time': sum(response_times) / len(response_times) if response_times else 0,
            'min_response_time': min(response_times) if response_times else 0,
            'max_response_time': max(response_times) if response_times else 0,
            'p95_response_time': self._percentile(response_times, 95) if response_times else 0,
            'p99_response_time': self._percentile(response_times, 99) if response_times else 0,
            'requests_per_second': len(successful_requests) / (max(r['timestamp'] for r in self.results) - min(r['timestamp'] for r in self.results)) if len(self.results) > 1 else 0
        }
        
        return analysis
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of a list"""
        sorted_data = sorted(data)
        index = int((percentile / 100) * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]
```

### 2. Benchmark Targets

#### Expected Performance Metrics
```python
# Performance targets for different scales
PERFORMANCE_TARGETS = {
    'small_batch': {  # 1-1000 URLs
        'max_processing_time': 300,  # 5 minutes
        'min_throughput_per_minute': 60,
        'max_error_rate': 0.02,  # 2%
        'max_memory_usage_mb': 2048
    },
    'medium_batch': {  # 1000-100000 URLs
        'max_processing_time': 3600,  # 1 hour
        'min_throughput_per_minute': 100,
        'max_error_rate': 0.05,  # 5%
        'max_memory_usage_mb': 4096
    },
    'large_batch': {  # 100000+ URLs
        'max_processing_time': 86400,  # 24 hours for 100k URLs
        'min_throughput_per_minute': 150,
        'max_error_rate': 0.1,  # 10%
        'max_memory_usage_mb': 8192
    }
}

def validate_performance(batch_size: int, actual_metrics: Dict) -> Dict:
    """Validate actual performance against targets"""
    if batch_size <= 1000:
        targets = PERFORMANCE_TARGETS['small_batch']
    elif batch_size <= 100000:
        targets = PERFORMANCE_TARGETS['medium_batch']
    else:
        targets = PERFORMANCE_TARGETS['large_batch']
    
    validation_results = {}
    
    for metric, target_value in targets.items():
        actual_value = actual_metrics.get(metric.replace('max_', '').replace('min_', ''))
        
        if metric.startswith('max_'):
            validation_results[metric] = {
                'target': target_value,
                'actual': actual_value,
                'passed': actual_value <= target_value if actual_value is not None else False
            }
        elif metric.startswith('min_'):
            validation_results[metric] = {
                'target': target_value,
                'actual': actual_value,
                'passed': actual_value >= target_value if actual_value is not None else False
            }
    
    validation_results['overall_passed'] = all(
        result['passed'] for result in validation_results.values() 
        if isinstance(result, dict)
    )
    
    return validation_results
```

## Troubleshooting Performance Issues

### 1. Common Performance Problems

#### High Memory Usage
```python
def diagnose_memory_issues():
    """Diagnose and fix memory-related performance issues"""
    import psutil
    import gc
    
    process = psutil.Process()
    memory_info = process.memory_info()
    memory_gb = memory_info.rss / (1024 ** 3)
    
    diagnostics = {
        'current_memory_gb': memory_gb,
        'memory_percent': process.memory_percent(),
        'garbage_objects': len(gc.get_objects()),
        'recommendations': []
    }
    
    if memory_gb > 6:  # High memory usage
        diagnostics['recommendations'].extend([
            'Reduce CHUNK_SIZE to decrease memory per chunk',
            'Reduce MAX_CONCURRENT_WORKERS to limit parallel processing',
            'Increase GC_FREQUENCY for more frequent garbage collection',
            'Consider using streaming processing for large datasets'
        ])
    
    if process.memory_percent() > 80:
        diagnostics['recommendations'].extend([
            'Immediate memory cleanup needed',
            'Consider restarting workers',
            'Check for memory leaks in image processing'
        ])
    
    return diagnostics
```

#### Low Throughput
```python
def diagnose_throughput_issues(metrics_history: List[PerformanceMetrics]):
    """Diagnose low throughput issues"""
    if len(metrics_history) < 5:
        return {'error': 'Insufficient metrics for analysis'}
    
    recent_metrics = metrics_history[-5:]
    avg_processing_rate = sum(m.processing_rate for m in recent_metrics) / len(recent_metrics)
    avg_error_rate = sum(m.error_rate for m in recent_metrics) / len(recent_metrics)
    avg_queue_size = sum(m.queue_size for m in recent_metrics) / len(recent_metrics)
    
    diagnostics = {
        'avg_processing_rate': avg_processing_rate,
        'avg_error_rate': avg_error_rate,
        'avg_queue_size': avg_queue_size,
        'recommendations': []
    }
    
    if avg_processing_rate < 50:  # Low throughput
        if avg_error_rate > 0.1:
            diagnostics['recommendations'].extend([
                'High error rate detected - check API key limits',
                'Review error logs for specific failure patterns',
                'Consider implementing exponential backoff',
                'Verify network connectivity to external APIs'
            ])
        
        if avg_queue_size > 1000:
            diagnostics['recommendations'].extend([
                'Large queue backlog - increase worker capacity',
                'Add more API keys to increase rate limits',
                'Increase MAX_CONCURRENT_WORKERS',
                'Consider horizontal scaling'
            ])
        
        diagnostics['recommendations'].extend([
            'Check database connection pool exhaustion',
            'Monitor Redis performance',
            'Verify Cloud Run/Function resource allocation',
            'Review network latency to external APIs'
        ])
    
    return diagnostics
```

#### Database Performance Issues
```sql
-- Database performance diagnostics
-- Run these queries to identify database bottlenecks

-- 1. Check for slow queries
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    rows
FROM pg_stat_statements 
ORDER BY total_time DESC 
LIMIT 10;

-- 2. Check for lock contention
SELECT 
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS current_statement_in_blocking_process
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;

-- 3. Check table statistics
SELECT 
    schemaname,
    tablename,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_live_tup,
    n_dead_tup,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;

-- 4. Check index usage
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_tup_read,
    idx_tup_fetch,
    idx_scan
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

### 2. Performance Optimization Checklist

#### Pre-deployment Checklist
```markdown
## Performance Optimization Checklist

### Infrastructure
- [ ] Cloud Function/Run resources allocated appropriately
- [ ] Database instance sized for expected load
- [ ] Redis instance configured with sufficient memory
- [ ] VPC connector configured for optimal networking
- [ ] Auto-scaling parameters configured

### Application Configuration
- [ ] Connection pools sized appropriately
- [ ] Worker counts optimized for available resources
- [ ] Chunk sizes balanced for memory vs throughput
- [ ] Rate limiting configured for API quotas
- [ ] Caching strategies implemented

### Database Optimization
- [ ] Indexes created for common query patterns
- [ ] Connection pool parameters tuned
- [ ] Vacuum and analyze scheduled
- [ ] Partitioning implemented for large tables

### Monitoring and Alerting
- [ ] Performance metrics collection enabled
- [ ] Alerting configured for key thresholds
- [ ] Log aggregation and analysis configured
- [ ] Dashboard created for operational visibility

### Testing and Validation
- [ ] Load testing completed
- [ ] Performance benchmarks validated
- [ ] Error handling tested under load
- [ ] Scalability limits documented
```

#### Post-deployment Monitoring
```python
def create_performance_alerts():
    """Create monitoring alerts for performance issues"""
    alerts = {
        'high_error_rate': {
            'metric': 'error_rate',
            'threshold': 0.1,  # 10%
            'duration': 300,   # 5 minutes
            'action': 'alert'
        },
        'low_throughput': {
            'metric': 'processing_rate',
            'threshold': 30,   # URLs per minute
            'duration': 600,   # 10 minutes
            'action': 'alert'
        },
        'high_memory': {
            'metric': 'memory_usage_percent',
            'threshold': 85,   # 85%
            'duration': 180,   # 3 minutes
            'action': 'scale_up'
        },
        'large_queue': {
            'metric': 'queue_size',
            'threshold': 5000,
            'duration': 600,   # 10 minutes
            'action': 'scale_up'
        },
        'database_slow_queries': {
            'metric': 'db_query_time_p95',
            'threshold': 5000,  # 5 seconds
            'duration': 300,    # 5 minutes
            'action': 'investigate'
        }
    }
    
    return alerts
```

## Conclusion

This comprehensive performance optimization guide provides a systematic approach to maximizing the performance of the Enterprise Image Analyzer system. The optimizations span infrastructure configuration, application tuning, database optimization, and monitoring strategies.

### Key Takeaways

1. **Cloud Resources**: Proper resource allocation and auto-scaling configuration are critical for handling variable workloads efficiently.

2. **Application Tuning**: Connection pooling, worker configuration, and memory management significantly impact throughput and reliability.

3. **Database Optimization**: Proper indexing, connection pooling, and query optimization are essential for high-performance data operations.

4. **Monitoring**: Comprehensive monitoring and alerting enable proactive performance management and issue resolution.

5. **Testing**: Regular performance testing and benchmark validation ensure the system maintains optimal performance as it scales.

### Next Steps

1. Implement the recommended configurations in a staging environment
2. Conduct thorough performance testing
3. Monitor metrics and adjust configurations based on actual workload patterns
4. Establish regular performance review cycles
5. Document lessons learned and update optimization strategies

For additional support or questions about performance optimization, refer to the monitoring dashboards, log analysis tools, and the troubleshooting sections in this guide.