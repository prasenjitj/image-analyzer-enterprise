# GPU Configuration Profiles for Dual A100 Setup

This document provides three configuration profiles for optimizing the image processing pipeline with dual NVIDIA A100-SXM4-40GB GPUs.

---

## Quick Reference

| Setting | Conservative | Medium | Aggressive |
|---------|-------------|--------|------------|
| **Workers** | 8 | 10 | 16 |
| **Concurrent Requests** | 8 | 12 | 20 |
| **GPU Generations** | 4 | 6 | 8 |
| **Rate Min/Max** | 4-20 | 6-30 | 8-50 |
| **Slow Threshold** | 60s | 45s | 30s |
| **Throughput** | ~1.5-2 req/s | ~3-4 req/s | ~5-8 req/s |
| **GPU Utilization** | 40-50% | 60-70% | 80-90% |
| **20M URLs ETA** | 120-150 days | 60-80 days | 30-45 days |
| **Risk of Timeouts** | Very Low | Low | Moderate |

---

## 🟢 CONSERVATIVE Profile (Stable, Low Risk)

**Best for:** Production environments, reliability over speed, overnight unattended processing

### Worker Configuration (`image-analyzer-enterprise/.env`)

```dotenv
# === WORKER CONFIGURATION ===
MAX_CONCURRENT_WORKERS=8
MAX_CONCURRENT_REQUESTS=8
MAX_CONCURRENT_BATCHES=10
MAX_CONCURRENT_CHUNKS=10
CHUNK_SIZE=100
CONNECTION_POOL_SIZE=100
ENABLE_KEEPALIVE=true

# === RESILIENCE (Very Tolerant) ===
RESILIENCE_INITIAL_RATE=6.0
RESILIENCE_MIN_RATE=4.0
RESILIENCE_MAX_RATE=20.0
RESILIENCE_MAX_CONCURRENT=16
RESILIENCE_MAX_QUEUE=500
TARGET_RESPONSE_TIME_MS=8000
SLOW_THRESHOLD_MS=60000
CRITICAL_THRESHOLD_MS=120000

# === RATE ADJUSTMENT (Gentle) ===
RATE_ADJUSTMENT_INTERVAL=15.0
RATE_WINDOW_SIZE=50
RATE_INCREASE_FACTOR=1.05
RATE_DECREASE_FACTOR=0.95
RATE_CRITICAL_DECREASE_FACTOR=0.8

# === CIRCUIT BREAKER (Tolerant) ===
CIRCUIT_FAILURE_THRESHOLD=100
CIRCUIT_SUCCESS_THRESHOLD=3
CIRCUIT_TIMEOUT_SECONDS=60
SLOW_CALL_THRESHOLD_MS=90000
TIMEOUT_FAILURE_WEIGHT=1.0

# === TIMEOUTS ===
REQUEST_TIMEOUT=180
QUEUE_TIMEOUT=300
RETRY_ATTEMPTS=3
RETRY_DELAY=2

# === PREFETCHING ===
ENABLE_PREFETCH=true
PREFETCH_QUEUE_SIZE=20
PREFETCH_CONCURRENT_DOWNLOADS=10
PREFETCH_DOWNLOAD_TIMEOUT=15.0
IMAGE_RESIZE_THREADS=4
```

### GPU Server Configuration (`llm_model/.env`)

```dotenv
# === GPU WORKER SETTINGS ===
MAX_CONCURRENT_GENERATIONS=4
MAX_INFERENCE_QUEUE_SIZE=500
MAX_INFERENCE_BATCH_SIZE=4
BATCH_WAIT_TIMEOUT=0.05
GEN_TIME_DEFAULT_EST=4.0

# === MEMORY MANAGEMENT ===
CLEAR_CACHE_EVERY_N_REQUESTS=50
ENABLE_MEMORY_DEFRAG=true

# === MODEL SETTINGS ===
USE_FP16=true
ENABLE_TF32=true
USE_FLASH_ATTENTION=true
MAX_NEW_TOKENS=128
```

### Expected Performance

- **Throughput:** ~1.5-2 requests/second
- **GPU Utilization:** 40-50%
- **Memory Usage:** ~16-17 GB per GPU
- **Stability:** Very High
- **Time for 20M URLs:** ~120-150 days

---

## 🟡 MEDIUM Profile (Balanced) - RECOMMENDED

**Best for:** Normal operations, good balance of speed and stability, monitored processing

### Worker Configuration (`image-analyzer-enterprise/.env`)

```dotenv
# === WORKER CONFIGURATION ===
MAX_CONCURRENT_WORKERS=10
MAX_CONCURRENT_REQUESTS=12
MAX_CONCURRENT_BATCHES=15
MAX_CONCURRENT_CHUNKS=15
CHUNK_SIZE=100
CONNECTION_POOL_SIZE=150
ENABLE_KEEPALIVE=true

# === RESILIENCE (Balanced) ===
RESILIENCE_INITIAL_RATE=10.0
RESILIENCE_MIN_RATE=6.0
RESILIENCE_MAX_RATE=30.0
RESILIENCE_MAX_CONCURRENT=24
RESILIENCE_MAX_QUEUE=1000
TARGET_RESPONSE_TIME_MS=5000
SLOW_THRESHOLD_MS=45000
CRITICAL_THRESHOLD_MS=90000

# === RATE ADJUSTMENT (Balanced) ===
RATE_ADJUSTMENT_INTERVAL=10.0
RATE_WINDOW_SIZE=100
RATE_INCREASE_FACTOR=1.08
RATE_DECREASE_FACTOR=0.92
RATE_CRITICAL_DECREASE_FACTOR=0.7

# === CIRCUIT BREAKER (Balanced) ===
CIRCUIT_FAILURE_THRESHOLD=75
CIRCUIT_SUCCESS_THRESHOLD=3
CIRCUIT_TIMEOUT_SECONDS=45
SLOW_CALL_THRESHOLD_MS=60000
TIMEOUT_FAILURE_WEIGHT=1.5

# === TIMEOUTS ===
REQUEST_TIMEOUT=120
QUEUE_TIMEOUT=240
RETRY_ATTEMPTS=2
RETRY_DELAY=1

# === PREFETCHING ===
ENABLE_PREFETCH=true
PREFETCH_QUEUE_SIZE=30
PREFETCH_CONCURRENT_DOWNLOADS=15
PREFETCH_DOWNLOAD_TIMEOUT=10.0
IMAGE_RESIZE_THREADS=4
```

### GPU Server Configuration (`llm_model/.env`)

```dotenv
# === GPU WORKER SETTINGS ===
MAX_CONCURRENT_GENERATIONS=6
MAX_INFERENCE_QUEUE_SIZE=1000
MAX_INFERENCE_BATCH_SIZE=4
BATCH_WAIT_TIMEOUT=0.08
GEN_TIME_DEFAULT_EST=3.5

# === MEMORY MANAGEMENT ===
CLEAR_CACHE_EVERY_N_REQUESTS=30
ENABLE_MEMORY_DEFRAG=true

# === MODEL SETTINGS ===
USE_FP16=true
ENABLE_TF32=true
USE_FLASH_ATTENTION=true
MAX_NEW_TOKENS=128
```

### Expected Performance

- **Throughput:** ~3-4 requests/second
- **GPU Utilization:** 60-70%
- **Memory Usage:** ~18-20 GB per GPU
- **Stability:** Good
- **Time for 20M URLs:** ~60-80 days

---

## 🔴 AGGRESSIVE Profile (Maximum Throughput)

**Best for:** Batch processing with active monitoring, speed over stability, short-term bursts

### Worker Configuration (`image-analyzer-enterprise/.env`)

```dotenv
# === WORKER CONFIGURATION ===
MAX_CONCURRENT_WORKERS=16
MAX_CONCURRENT_REQUESTS=20
MAX_CONCURRENT_BATCHES=25
MAX_CONCURRENT_CHUNKS=25
CHUNK_SIZE=150
CONNECTION_POOL_SIZE=250
ENABLE_KEEPALIVE=true

# === RESILIENCE (Aggressive) ===
RESILIENCE_INITIAL_RATE=15.0
RESILIENCE_MIN_RATE=8.0
RESILIENCE_MAX_RATE=50.0
RESILIENCE_MAX_CONCURRENT=40
RESILIENCE_MAX_QUEUE=2000
TARGET_RESPONSE_TIME_MS=4000
SLOW_THRESHOLD_MS=30000
CRITICAL_THRESHOLD_MS=60000

# === RATE ADJUSTMENT (Aggressive) ===
RATE_ADJUSTMENT_INTERVAL=8.0
RATE_WINDOW_SIZE=150
RATE_INCREASE_FACTOR=1.12
RATE_DECREASE_FACTOR=0.90
RATE_CRITICAL_DECREASE_FACTOR=0.6

# === CIRCUIT BREAKER (Aggressive) ===
CIRCUIT_FAILURE_THRESHOLD=50
CIRCUIT_SUCCESS_THRESHOLD=5
CIRCUIT_TIMEOUT_SECONDS=30
SLOW_CALL_THRESHOLD_MS=45000
TIMEOUT_FAILURE_WEIGHT=2.0

# === TIMEOUTS ===
REQUEST_TIMEOUT=90
QUEUE_TIMEOUT=180
RETRY_ATTEMPTS=2
RETRY_DELAY=0.5

# === PREFETCHING ===
ENABLE_PREFETCH=true
PREFETCH_QUEUE_SIZE=50
PREFETCH_CONCURRENT_DOWNLOADS=25
PREFETCH_DOWNLOAD_TIMEOUT=8.0
IMAGE_RESIZE_THREADS=6
```

### GPU Server Configuration (`llm_model/.env`)

```dotenv
# === GPU WORKER SETTINGS ===
MAX_CONCURRENT_GENERATIONS=8
MAX_INFERENCE_QUEUE_SIZE=2000
MAX_INFERENCE_BATCH_SIZE=8
BATCH_WAIT_TIMEOUT=0.1
GEN_TIME_DEFAULT_EST=3.0

# === MEMORY MANAGEMENT ===
CLEAR_CACHE_EVERY_N_REQUESTS=25
ENABLE_MEMORY_DEFRAG=true

# === MODEL SETTINGS ===
USE_FP16=true
ENABLE_TF32=true
USE_FLASH_ATTENTION=true
MAX_NEW_TOKENS=128
```

### Expected Performance

- **Throughput:** ~5-8 requests/second
- **GPU Utilization:** 80-90%
- **Memory Usage:** ~22-25 GB per GPU
- **Stability:** Moderate (requires monitoring)
- **Time for 20M URLs:** ~30-45 days

---

## How to Apply a Profile

### Step 1: Update Worker Configuration

```bash
cd /home/prasenjitjana/image-analyzer-enterprise

# Edit .env with your chosen profile values
nano .env

# Restart worker service
sudo systemctl restart image-analyzer-workers.service
```

### Step 2: Update GPU Server Configuration

```bash
cd /home/prasenjitjana/llm_model

# Edit .env with your chosen profile values
nano .env

# Restart BOTH GPU services
sudo systemctl restart qwen-vl-api-gpu-0.service qwen-vl-api-gpu-1.service
```

### Step 3: Verify Services

```bash
# Check all services are running
systemctl is-active qwen-vl-api-gpu-0.service qwen-vl-api-gpu-1.service image-analyzer-workers.service

# Check GPU health
curl -s http://localhost:8000/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'GPU0: workers={d.get(\"workers\")}, queue={d.get(\"queue_size\")}')"
curl -s http://localhost:8001/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'GPU1: workers={d.get(\"workers\")}, queue={d.get(\"queue_size\")}')"
```

---

## Monitoring Commands

### Real-time GPU Utilization

```bash
watch -n 2 'nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader'
```

### Worker Rate Limiter Status

```bash
sudo journalctl -u image-analyzer-workers.service -f | grep -E "Rate|processed|success|failed"
```

### GPU Response Times

```bash
# GPU 0
sudo journalctl -u qwen-vl-api-gpu-0.service -f | grep "processed in"

# GPU 1
sudo journalctl -u qwen-vl-api-gpu-1.service -f | grep "processed in"
```

### Database Processing Stats

```bash
PGPASSWORD='testpass123' psql -h localhost -U prasenjitjana -d imageprocessing -c "
SELECT 
    DATE_TRUNC('minute', created_at) as minute,
    COUNT(*) as urls_processed
FROM url_analysis_results 
WHERE created_at > NOW() - INTERVAL '10 minutes'
GROUP BY DATE_TRUNC('minute', created_at)
ORDER BY minute DESC
LIMIT 10;
"
```

### Queue Stats

```bash
redis-cli info | grep -E "keys|memory"
```

---

## Troubleshooting

### Rate Keeps Dropping to Minimum

**Cause:** Response times exceeding `SLOW_THRESHOLD_MS`

**Solutions:**
1. Increase `SLOW_THRESHOLD_MS` (e.g., 60000 → 90000)
2. Decrease `MAX_CONCURRENT_REQUESTS` to reduce queuing
3. Increase `RESILIENCE_MIN_RATE` to prevent floor

### High GPU Memory Usage

**Cause:** KV cache growth or memory fragmentation

**Solutions:**
1. Decrease `CLEAR_CACHE_EVERY_N_REQUESTS` (e.g., 50 → 25)
2. Restart GPU services to clear memory
3. Reduce `MAX_CONCURRENT_GENERATIONS`

### Frequent Timeouts

**Cause:** Too many concurrent requests overwhelming GPUs

**Solutions:**
1. Use CONSERVATIVE profile
2. Increase `REQUEST_TIMEOUT`
3. Reduce `MAX_CONCURRENT_REQUESTS` and `RESILIENCE_MAX_CONCURRENT`

### Circuit Breaker Opening

**Cause:** Too many failures or timeouts

**Solutions:**
1. Increase `CIRCUIT_FAILURE_THRESHOLD`
2. Increase `CIRCUIT_TIMEOUT_SECONDS`
3. Check GPU service health

---

## Configuration Parameter Reference

### Worker Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MAX_CONCURRENT_WORKERS` | Number of background worker processes | 8 |
| `MAX_CONCURRENT_REQUESTS` | Max parallel API requests per worker | 16 |
| `RESILIENCE_INITIAL_RATE` | Starting requests per second | 8.0 |
| `RESILIENCE_MIN_RATE` | Minimum rate floor | 2.0 |
| `RESILIENCE_MAX_RATE` | Maximum rate ceiling | 30.0 |
| `SLOW_THRESHOLD_MS` | Response time triggering rate reduction | 30000 |
| `CRITICAL_THRESHOLD_MS` | Response time triggering critical reduction | 60000 |

### GPU Server Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `MAX_CONCURRENT_GENERATIONS` | Parallel inference workers per GPU | 4 |
| `MAX_INFERENCE_QUEUE_SIZE` | Max queued requests before 429 | 500 |
| `BATCH_WAIT_TIMEOUT` | Seconds to wait for batch formation | 0.05 |
| `CLEAR_CACHE_EVERY_N_REQUESTS` | Frequency of GPU cache clearing | 50 |

---

*Last updated: November 26, 2025*
