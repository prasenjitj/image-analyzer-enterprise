# Throughput Optimization Guide

This document describes the optimizations made to align `image-analyzer-enterprise` with the high-throughput capabilities of the `llm_model` API.

## LLM Model Capabilities (Reference)

The `/llm_model/app.py` is optimized for high throughput with:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `MAX_CONCURRENT_GENERATIONS` | 16 | Number of inference workers |
| `MAX_INFERENCE_BATCH_SIZE` | 16 | Max requests batched together |
| `MAX_INFERENCE_QUEUE_SIZE` | 500 | Max queued requests |
| Rate Limit | 1000/min | API rate limit |
| GPU Optimizations | Flash Attention 2, TF32, SDPA | Hardware acceleration |

## Optimizations Applied to Image Analyzer

### 1. Processing Parallelism (enterprise_config.py)

**Before:**
```python
max_concurrent_workers = 5
max_concurrent_requests = 1  # MAJOR BOTTLENECK
requests_per_minute = 100
chunk_size = 1000
max_concurrent_chunks = 1
```

**After:**
```python
max_concurrent_workers = 16      # Match LLM model's 16 inference workers
max_concurrent_requests = 16     # Allow 16 parallel URL requests per worker
requests_per_minute = 800        # 80% of LLM model's 1000/min capacity
chunk_size = 500                 # Smaller chunks for better parallelism
max_concurrent_chunks = 4        # Process 4 chunks in parallel
```

### 2. Connection Pooling (processor.py)

**Before:**
```python
connector = aiohttp.TCPConnector(
    limit=self.max_workers,           # 5 connections
    limit_per_host=self.max_workers   # 5 per host
)
```

**After:**
```python
connector = aiohttp.TCPConnector(
    limit=100,                    # Large pool for high throughput
    limit_per_host=32,            # 32 connections to LLM API
    keepalive_timeout=30,         # Reuse connections
    force_close=False             # Keep connections alive
)
```

### 3. Batch Processing (processor.py)

**Before:**
- Sequential processing with 100 URL sub-batches
- Limited concurrency (5)

**After:**
- 200 URL sub-batches for better LLM model batching
- 16 concurrent requests matching LLM model capacity
- Throughput metrics logging

### 4. Timeout Optimization (enterprise_config.py)

**Before:**
```python
request_timeout = 150  # Very long timeout
retry_delay = 2.0
```

**After:**
```python
request_timeout = 90   # Reduced since LLM model processes quickly
retry_delay = 1.0      # Faster retries
```

## Expected Throughput Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Concurrent Requests | 5 | 16 | 3.2x |
| Requests/Minute | 100 | 800 | 8x |
| Parallel Chunks | 1 | 4 | 4x |
| URLs per Batch | 100 | 200 | 2x |

**Theoretical Maximum Throughput:**
- Before: ~100 URLs/minute
- After: ~800 URLs/minute

## Environment Variables

Override defaults via environment:

```bash
# High throughput configuration
export MAX_CONCURRENT_WORKERS=16
export MAX_CONCURRENT_REQUESTS=16
export MAX_CONCURRENT_CHUNKS=4
export CHUNK_SIZE=500
export REQUESTS_PER_MINUTE=800
export REQUEST_TIMEOUT=90
export CONNECTION_POOL_SIZE=100
export ENABLE_KEEPALIVE=true

# API endpoint
export API_ENDPOINT_URL=http://your-llm-api:8000/generate
```

## Monitoring Throughput

Check processing throughput in logs:

```
INFO: Batch completed: 200 URLs in 25.00s (8.0 URLs/sec), 195 successful
INFO: Queued 4 chunks for parallel processing (max_concurrent_chunks=4)
INFO: ChunkProcessor worker-1 initialized with 16 concurrent requests
```

## Tuning for Your Environment

Adjust based on your infrastructure:

1. **Limited RAM:** Reduce `CHUNK_SIZE` to 250-300
2. **Network constraints:** Lower `CONNECTION_POOL_SIZE` to 50
3. **LLM API overload:** Reduce `REQUESTS_PER_MINUTE` to 400-600
4. **Multiple batches:** Increase `MAX_CONCURRENT_BATCHES` to 10

## Compatibility

These optimizations are backward compatible:
- Default values work without environment changes
- Existing batch data structures unchanged
- API contracts maintained
