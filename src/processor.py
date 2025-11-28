"""
Image processing module using OpenRouter API for enterprise batch processing.

This module processes images through OpenRouter's API (using Qwen 2.5 VL or presets)
for storefront identification and business information extraction.

Features:
- OpenRouter integration with SDK and HTTP fallback
- Resilience patterns (circuit breaker, rate limiting, backpressure)
- Image prefetching for improved throughput
- Connection pooling and async processing
"""
import asyncio
import aiohttp
import logging
import time
import hashlib
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json
import os
from io import BytesIO
from PIL import Image, ImageOps
from concurrent.futures import ThreadPoolExecutor
try:
    # OpenAI package is used as the client for OpenRouter (OpenAI-compatible API)
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except Exception:
    OpenAI = None
    _OPENAI_AVAILABLE = False

from .enterprise_config import config
from .resilience import get_resilient_client

logger = logging.getLogger(__name__)

# =====================================================
# PREFETCH CONFIGURATION
# =====================================================
# Number of images to prefetch ahead of current processing
PREFETCH_QUEUE_SIZE = int(os.environ.get('PREFETCH_QUEUE_SIZE', '20'))
# Max concurrent image downloads for prefetching
PREFETCH_CONCURRENT_DOWNLOADS = int(
    os.environ.get('PREFETCH_CONCURRENT_DOWNLOADS', '10'))
# Timeout for prefetch downloads (shorter than main timeout)
PREFETCH_DOWNLOAD_TIMEOUT = float(
    os.environ.get('PREFETCH_DOWNLOAD_TIMEOUT', '10.0'))
# Enable/disable prefetching
ENABLE_PREFETCH = os.environ.get(
    'ENABLE_PREFETCH', 'true').lower() in ('1', 'true', 'yes')
# Thread pool for CPU-bound image resizing
IMAGE_RESIZE_THREADS = int(os.environ.get('IMAGE_RESIZE_THREADS', '4'))


@dataclass
class ProcessingResult:
    """Result of image processing with optional listing data"""
    url: str
    success: bool
    analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    cache_hit: bool = False
    phone_number: bool = False
    # Added for listing data support
    listing_data: Optional[Dict[str, Any]] = None


@dataclass
class PrefetchedImage:
    """Container for prefetched and preprocessed image data"""
    url: str
    image_bytes: Optional[bytes] = None
    error: Optional[str] = None
    download_time: float = 0.0
    resize_time: float = 0.0
    original_size: Optional[Tuple[int, int]] = None
    final_size: Optional[Tuple[int, int]] = None


class ImagePrefetcher:
    """
    Asynchronous image prefetcher that downloads and resizes images ahead of time.

    This allows the GPU to process images continuously while the next batch
    is being downloaded and preprocessed in parallel.
    """

    def __init__(self, session: aiohttp.ClientSession, max_queue_size: int = PREFETCH_QUEUE_SIZE):
        self.session = session
        self.max_queue_size = max_queue_size
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size * 2)
        self._prefetch_cache: Dict[str, PrefetchedImage] = {}
        self._cache_lock = asyncio.Lock()
        self._prefetch_tasks: List[asyncio.Task] = []
        self._shutdown = False
        self._download_semaphore = asyncio.Semaphore(
            PREFETCH_CONCURRENT_DOWNLOADS)
        self._resize_executor = ThreadPoolExecutor(
            max_workers=IMAGE_RESIZE_THREADS)
        self._stats = {
            'prefetch_hits': 0,
            'prefetch_misses': 0,
            'total_download_time': 0.0,
            'total_resize_time': 0.0,
        }

    async def start(self):
        """Start the prefetch worker tasks"""
        if not ENABLE_PREFETCH:
            logger.info("Image prefetching disabled")
            return

        logger.info(
            f"Starting image prefetcher (queue_size={self.max_queue_size}, concurrent={PREFETCH_CONCURRENT_DOWNLOADS})")
        self._shutdown = False

        # Start multiple prefetch workers
        for i in range(PREFETCH_CONCURRENT_DOWNLOADS):
            task = asyncio.create_task(self._prefetch_worker(i))
            self._prefetch_tasks.append(task)

    async def stop(self):
        """Stop the prefetch workers and cleanup"""
        self._shutdown = True

        # Cancel all prefetch tasks
        for task in self._prefetch_tasks:
            task.cancel()

        if self._prefetch_tasks:
            await asyncio.gather(*self._prefetch_tasks, return_exceptions=True)

        self._prefetch_tasks.clear()
        self._prefetch_cache.clear()
        self._resize_executor.shutdown(wait=False)

        logger.info(
            f"Prefetcher stopped. Stats: hits={self._stats['prefetch_hits']}, misses={self._stats['prefetch_misses']}")

    async def schedule_prefetch(self, urls: List[str]):
        """Schedule URLs for prefetching"""
        if not ENABLE_PREFETCH:
            return

        for url in urls:
            # Skip if already in cache or queue is full
            async with self._cache_lock:
                if url in self._prefetch_cache:
                    continue

            try:
                self._queue.put_nowait(url)
            except asyncio.QueueFull:
                # Queue full, skip prefetching this URL
                break

    async def get_prefetched(self, url: str) -> Optional[PrefetchedImage]:
        """Get a prefetched image if available, otherwise return None"""
        async with self._cache_lock:
            if url in self._prefetch_cache:
                self._stats['prefetch_hits'] += 1
                return self._prefetch_cache.pop(url)
            else:
                self._stats['prefetch_misses'] += 1
                return None

    async def _prefetch_worker(self, worker_id: int):
        """Worker that continuously prefetches images from the queue"""
        while not self._shutdown:
            try:
                # Get URL from queue with timeout
                try:
                    url = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Check if already cached
                async with self._cache_lock:
                    if url in self._prefetch_cache:
                        continue

                # Download and resize the image
                prefetched = await self._download_and_resize(url)

                # Store in cache
                async with self._cache_lock:
                    # Limit cache size
                    if len(self._prefetch_cache) >= self.max_queue_size:
                        # Remove oldest entry
                        if self._prefetch_cache:
                            oldest_key = next(iter(self._prefetch_cache))
                            del self._prefetch_cache[oldest_key]

                    self._prefetch_cache[url] = prefetched

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Prefetch worker {worker_id} error: {e}")

    async def _download_and_resize(self, url: str) -> PrefetchedImage:
        """Download and resize an image"""
        result = PrefetchedImage(url=url)

        download_start = time.perf_counter()

        try:
            async with self._download_semaphore:
                timeout = aiohttp.ClientTimeout(
                    total=PREFETCH_DOWNLOAD_TIMEOUT)
                async with self.session.get(url, timeout=timeout) as response:
                    if response.status != 200:
                        result.error = f"HTTP {response.status}"
                        return result

                    # Check content length
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > 10 * 1024 * 1024:
                        result.error = "Image too large"
                        return result

                    img_bytes = await response.read()

            result.download_time = time.perf_counter() - download_start
            self._stats['total_download_time'] += result.download_time

            # Resize in thread pool to not block event loop
            resize_start = time.perf_counter()
            loop = asyncio.get_running_loop()

            resized_bytes, original_size, final_size = await loop.run_in_executor(
                self._resize_executor,
                self._resize_image_sync,
                img_bytes
            )

            result.resize_time = time.perf_counter() - resize_start
            self._stats['total_resize_time'] += result.resize_time
            result.image_bytes = resized_bytes
            result.original_size = original_size
            result.final_size = final_size

        except asyncio.TimeoutError:
            result.error = "Download timeout"
        except Exception as e:
            result.error = str(e)

        return result

    @staticmethod
    def _resize_image_sync(img_bytes: bytes) -> Tuple[bytes, Tuple[int, int], Tuple[int, int]]:
        """Synchronous image resize (runs in thread pool)"""
        try:
            with Image.open(BytesIO(img_bytes)) as img:
                img = ImageOps.exif_transpose(img)
                original_size = img.size

                max_size = 512
                original_w, original_h = img.size

                if original_w > max_size or original_h > max_size:
                    # Calculate scale to fit within max_size
                    scale = min(max_size / original_w, max_size / original_h)
                    new_w = max(1, int(original_w * scale))
                    new_h = max(1, int(original_h * scale))

                    img = img.convert('RGB')
                    img = img.resize((new_w, new_h), Image.LANCZOS)

                    # Pad to 512x512 square
                    square = Image.new('RGB', (512, 512), (255, 255, 255))
                    paste_x = (512 - img.width) // 2
                    paste_y = (512 - img.height) // 2
                    square.paste(img, (paste_x, paste_y))
                    img = square
                else:
                    img = img.convert('RGB')

                # Save to bytes
                out_buf = BytesIO()
                img.save(out_buf, format='JPEG', quality=85, optimize=True)
                out_buf.seek(0)

                return out_buf.read(), original_size, img.size

        except Exception as e:
            raise ValueError(f"Image processing failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get prefetcher statistics"""
        total = self._stats['prefetch_hits'] + self._stats['prefetch_misses']
        hit_rate = self._stats['prefetch_hits'] / total if total > 0 else 0

        return {
            'enabled': ENABLE_PREFETCH,
            'queue_size': self._queue.qsize() if hasattr(self._queue, 'qsize') else 0,
            'cache_size': len(self._prefetch_cache),
            'prefetch_hits': self._stats['prefetch_hits'],
            'prefetch_misses': self._stats['prefetch_misses'],
            'hit_rate': round(hit_rate * 100, 1),
            'avg_download_time': round(self._stats['total_download_time'] / max(1, total), 3),
            'avg_resize_time': round(self._stats['total_resize_time'] / max(1, total), 3),
        }


class ImageProcessor:
    """Enterprise image processor using OpenRouter API with resilience patterns"""

    def __init__(self, api_keys: List[str] = None, max_workers: Optional[int] = None):
        self.api_keys = api_keys or []  # Legacy compatibility - not used with OpenRouter
        self.max_workers = max_workers if max_workers is not None else getattr(
            config, 'max_concurrent_workers', 5)
        self.current_api_key_index = 0
        self.session: Optional[aiohttp.ClientSession] = None
        self._client_timeout: Optional[aiohttp.ClientTimeout] = None

        # Legacy API endpoint index for round-robin load balancing
        self._legacy_endpoint_index = 0

        # OpenAI client for OpenRouter (initialize lazily only when available)
        self.openai_client = None
        if _OPENAI_AVAILABLE and getattr(config, 'openrouter_api_key', None):
            try:
                self.openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=config.openrouter_api_key,
                )
                logger.info("OpenRouter client initialized")
            except Exception as e:
                logger.warning(
                    "Failed to initialize OpenRouter client: %s", repr(e))
                self.openai_client = None

        # Log legacy API endpoints if using legacy backend
        if getattr(config, 'api_backend', 'openrouter') == 'legacy':
            endpoints = config.legacy_api_endpoints_list
            logger.info(f"Legacy API endpoints configured: {endpoints}")

        # Image prefetcher for pipelining downloads with inference
        self._prefetcher: Optional[ImagePrefetcher] = None

        # Initialize resilient API client
        self._init_resilience()

        logger.info(
            f"ImageProcessor initialized (max_workers={self.max_workers})")
        logger.info(
            f"Resilience enabled: circuit_breaker, adaptive_rate_limiter, backpressure_queue")
        logger.info(
            f"Prefetching: {'enabled' if ENABLE_PREFETCH else 'disabled'} (queue={PREFETCH_QUEUE_SIZE}, concurrent={PREFETCH_CONCURRENT_DOWNLOADS})")

    def _init_resilience(self):
        """Initialize resilience patterns - uses SHARED global client for cross-worker coordination"""
        # Use the shared/global resilient client so all workers share the same rate limiter
        # This prevents each worker from independently sending requests at max rate
        # which would overwhelm the GPU queues when running multiple workers
        self.resilient_client = get_resilient_client()

        logger.info(
            f"Using shared resilient client (rate={self.resilient_client.rate_limiter._current_rate:.1f}/s, "
            f"max_concurrent={self.resilient_client.backpressure_queue.config.max_concurrent})"
        )

    def start_processing(self):
        """Initialize processing session - Optimized for high throughput"""
        if not self.session:
            # Use a TCPConnector with high limits for throughput
            # connection_pool_size from config (default 100) allows many concurrent connections
            # keepalive_timeout helps reuse connections for subsequent requests
            pool_size = getattr(config, 'connection_pool_size', 100)
            enable_keepalive = getattr(config, 'enable_keepalive', True)

            connector = aiohttp.TCPConnector(
                limit=pool_size,
                limit_per_host=pool_size,  # Allow many connections to the LLM API
                enable_cleanup_closed=True,
                keepalive_timeout=30 if enable_keepalive else 0,
                force_close=not enable_keepalive,
                # DNS caching for faster connection reuse
                ttl_dns_cache=300,
                # Use happy eyeballs for faster connection establishment
                happy_eyeballs_delay=0.25,
            )

            # Configure timeouts - use shorter timeouts since LLM model processes quickly
            request_timeout = getattr(config, 'request_timeout', 90)
            connect_timeout = min(10, max(1, int(request_timeout)))
            sock_read = max(30, int(request_timeout))

            timeout = aiohttp.ClientTimeout(
                total=request_timeout,
                connect=connect_timeout,
                sock_connect=connect_timeout,
                sock_read=sock_read
            )

            # store for per-request usage
            self._client_timeout = timeout
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
            logger.info(
                "Started aiohttp session (pool_size=%d, keepalive=%s, timeout=%ss)",
                pool_size, enable_keepalive, request_timeout
            )

            # Initialize prefetcher with the session
            if ENABLE_PREFETCH and not self._prefetcher:
                self._prefetcher = ImagePrefetcher(
                    self.session, max_queue_size=PREFETCH_QUEUE_SIZE)
                # Start prefetcher in background
                asyncio.create_task(self._prefetcher.start())

    async def stop_processing(self):
        """Clean up processing session"""
        # Stop prefetcher first
        if self._prefetcher:
            await self._prefetcher.stop()
            self._prefetcher = None

        if self.session:
            await self.session.close()
            self.session = None

    def get_resilience_stats(self) -> Dict[str, Any]:
        """Get current resilience pattern statistics"""
        stats = self.resilient_client.get_stats()

        # Add prefetcher stats
        if self._prefetcher:
            stats['prefetcher'] = self._prefetcher.get_stats()
        else:
            stats['prefetcher'] = {'enabled': False}

        return stats

    async def reset_resilience(self):
        """Reset resilience patterns (useful after recovery)"""
        await self.resilient_client.reset()

    def get_next_api_key(self) -> str:
        """Get next API key (round-robin) - kept for compatibility"""
        if not self.api_keys:
            return ""
        api_key = self.api_keys[self.current_api_key_index]
        self.current_api_key_index = (
            self.current_api_key_index + 1) % len(self.api_keys)
        return api_key

    async def _download_and_resize_image(self, image_url: str, always_upload: bool = False) -> Optional[bytes]:
        """Download image and resize to max 512x512 for efficient API processing.

        Returns resized image bytes (JPEG) when resizing occurred or always_upload is True,
        or None when download failed or resizing was not necessary.

        Uses prefetched images when available for better throughput.
        """
        # Check prefetch cache first for pre-downloaded/resized image
        if self._prefetcher and ENABLE_PREFETCH:
            prefetched = await self._prefetcher.get_prefetched(image_url)
            if prefetched:
                if prefetched.error:
                    logger.debug(
                        f"Prefetch error for {image_url}: {prefetched.error}")
                    # Fall through to regular download
                elif prefetched.image_bytes:
                    logger.debug(
                        f"Using prefetched image for {image_url} "
                        f"(download={prefetched.download_time:.2f}s, resize={prefetched.resize_time:.2f}s)"
                    )
                    return prefetched.image_bytes

        # Ensure we have a session
        if not self.session or getattr(self.session, 'closed', False):
            self.start_processing()

        try:
            # Use shorter timeout for image download (15 seconds max)
            download_timeout = aiohttp.ClientTimeout(total=15)
            async with self.session.get(image_url, timeout=download_timeout) as img_resp:
                if img_resp.status != 200:
                    logger.debug(
                        'Image download returned non-200 %s for %s', img_resp.status, image_url)
                    return None

                # Check content length before downloading (10MB max)
                content_length = img_resp.headers.get('Content-Length')
                if content_length and int(content_length) > 10 * 1024 * 1024:
                    logger.warning(
                        "Image too large to download: %s (%s bytes)", image_url, content_length)
                    return None

                img_bytes = await img_resp.read()

                try:
                    with Image.open(BytesIO(img_bytes)) as img:
                        img = ImageOps.exif_transpose(img)
                        original_w, original_h = img.size

                        # Target size - constrain to 512x512 max
                        max_size = 512
                        needs_resize = original_w > max_size or original_h > max_size

                        if needs_resize:
                            # Calculate scale to fit BOTH dimensions within max_size
                            scale = min(max_size / original_w,
                                        max_size / original_h)
                            new_w = max(1, int(original_w * scale))
                            new_h = max(1, int(original_h * scale))

                            img = img.convert('RGB')
                            img = img.resize((new_w, new_h), Image.LANCZOS)

                            # Pad to 512x512 square with white background
                            square = Image.new(
                                'RGB', (512, 512), (255, 255, 255))
                            paste_x = (512 - img.width) // 2
                            paste_y = (512 - img.height) // 2
                            square.paste(img, (paste_x, paste_y))

                            out_buf = BytesIO()
                            square.save(out_buf, format='JPEG',
                                        quality=85, optimize=True)
                            out_buf.seek(0)

                            logger.debug(
                                'Resized image %s from %dx%d to %dx%d (padded to 512x512)',
                                image_url, original_w, original_h, new_w, new_h
                            )
                            return out_buf.read()

                        # If caller requested always_upload, return the image
                        # bytes (converted to JPEG) even when not resized.
                        if always_upload:
                            img = img.convert('RGB')
                            out_buf = BytesIO()
                            img.save(out_buf, format='JPEG',
                                     quality=85, optimize=True)
                            out_buf.seek(0)
                            return out_buf.read()

                except Exception:
                    logger.debug(
                        'Failed to open/process downloaded image for %s', image_url)
                    return None

        except asyncio.TimeoutError:
            logger.warning("Timeout downloading image: %s", image_url)
            return None
        except Exception:
            logger.debug(
                'Failed to download image for local processing: %s', image_url)
            return None

        return None

    async def process_batch(self, urls: List[str]) -> List[ProcessingResult]:
        """Process a batch of URLs with prefetching optimization and throttled concurrency"""
        # Ensure session is initialized and valid
        if not self.session or self.session.closed:
            if self.session and self.session.closed:
                self.session = None
            self.start_processing()

        # Schedule prefetching for all URLs upfront
        # This starts downloading images while we process the first ones
        if self._prefetcher and ENABLE_PREFETCH:
            await self._prefetcher.schedule_prefetch(urls)
            logger.debug(f"Scheduled prefetch for {len(urls)} URLs")

        # THROTTLED PROCESSING: Limit concurrent requests per worker
        # With 10 workers and 32 total slots, each worker should only have 3-4 concurrent
        # This prevents overwhelming the shared backpressure queue
        MAX_CONCURRENT_PER_BATCH = int(
            os.getenv('MAX_CONCURRENT_PER_BATCH', '4'))
        batch_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PER_BATCH)

        async def throttled_process(url: str) -> ProcessingResult:
            async with batch_semaphore:
                return await self.process_single_url(url)

        # Create tasks with per-batch throttling
        tasks = [asyncio.create_task(throttled_process(url)) for url in urls]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(ProcessingResult(
                    url=urls[i],
                    success=False,
                    error=str(result),
                    processing_time=0.0
                ))
            else:
                processed_results.append(result)

        return processed_results

    async def process_single_url(self, url: str) -> ProcessingResult:
        """Process a single image URL"""
        start_time = time.time()

        try:
            logger.debug("Processing single URL: %s", url)
            # Ensure processing session is available before attempting to
            # download/resize images locally. This covers cases where
            # `process_single_url` was called directly without prior
            # `start_processing()`.
            if not self.session or getattr(self.session, 'closed', False):
                self.start_processing()
            # Process image with API endpoint
            analysis = await self._analyze_image(url)

            return ProcessingResult(
                url=url,
                success=True,
                analysis=analysis,
                processing_time=time.time() - start_time,
                phone_number=analysis.get('phone_number', False)
            )

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return ProcessingResult(
                url=url,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )

    async def _analyze_image(self, image_url: str) -> Dict[str, Any]:
        """Analyze image using OpenRouter API with resilience patterns"""

        # Check circuit breaker state first (fast fail)
        if self.resilient_client.circuit_breaker.is_open:
            # Circuit is open - check if we can proceed
            if not await self.resilient_client.circuit_breaker.can_execute():
                raise Exception(
                    f"Circuit breaker OPEN - API is overwhelmed. Rejecting request for {image_url}. "
                    f"Will retry after recovery period."
                )

        # Acquire permission through all resilience gates
        # Use 300s timeout - with 32 concurrent slots and ~4s per request, queue clears fast
        request_start_time = time.time()
        acquired = await self.resilient_client.acquire(timeout=300.0)

        if not acquired:
            # Request was rejected by one of the resilience patterns
            stats = self.resilient_client.get_stats()
            raise Exception(
                f"Request rejected by resilience layer for {image_url}. "
                f"Circuit: {stats['circuit_breaker']['state']}, "
                f"Queue: {stats['backpressure_queue']['in_flight']}/{stats['backpressure_queue']['max_concurrent']}, "
                f"Rate: {stats['rate_limiter']['current_rate']:.1f}/s"
            )

        try:
            # Proceed with the actual API call
            result = await self._make_api_request(image_url, request_start_time)
            return result
        finally:
            # Always release the backpressure slot
            await self.resilient_client.release()

    async def _make_api_request(self, image_url: str, request_start_time: float) -> Dict[str, Any]:
        """Make the API call based on configured backend and normalize the JSON response"""

        api_backend = getattr(config, 'api_backend', 'openrouter')

        if api_backend == "legacy":
            # Use legacy API endpoint
            if not getattr(config, 'legacy_api_endpoint', None):
                raise Exception(
                    "Legacy API not configured. Set LEGACY_API_ENDPOINT.")
        else:
            # Use OpenRouter (default)
            if not self.openai_client and not getattr(config, 'openrouter_api_key', None):
                raise Exception(
                    "OpenRouter client not configured. Set OPENROUTER_API_KEY and/or install the openai SDK.")

        prompt = """
            You are an image analysis model. Carefully examine the image and determine whether it shows a physical store or business establishment. 
            **The main subject of the image must be a store front or business entrance with a clearly visible storefront. If the store is not the primary subject (e.g., barely visible, background only, cropped, partial, or obstructed), do NOT set `store_image` to true.** Respond strictly in JSON format only — no additional words, notes, or explanations.
            {
            "store_image": true/false/"No Result",
            "text_content": "Uniquely visible text in the image (e.g., on boards, signboards, banners)",
            "store_name": "Name of the store if visible, else empty string",
            "business_contact": "Phone number if visible, else empty string",
            "image_description": "Brief factual description of what the image shows"
            }

            Rules & Guidelines:

            1. **store_image**

            * **true** → only if the *main subject* of the image is a clearly visible physical store, shop, restaurant, stall, or similar business with an identifiable storefront.
            * **false** → if the image does not show a store, OR if a store exists but is not the main subject (e.g., in the background, partially cropped, too far away, obstructed, or indistinct).
            * **"No Result"** → if the image is too unclear or ambiguous to decide.

            2. **text_content**

            * Include only actual visible text from signboards, banners, or storefronts.
            * If no text is visible, use an empty string.

            3. **store_name & business_contact**

            * Extract ONLY from visible text.
            * Do not infer or guess.
            * Use empty string if not visible.

            4. **image_description**

            * Keep short, factual, objective.
            * Describe only what is visible — no assumptions.

            5. **Output requirements**

            * Output only the JSON object.
            * No markdown, comments, extra text, or explanations before or after.
        """.strip()

        attempts = max(1, getattr(config, 'retry_attempts', 3))
        last_exception = None
        response_text = None

        # Select API backend
        backend_name = "Legacy API" if api_backend == "legacy" else "OpenRouter"

        for attempt in range(attempts):
            try:
                if api_backend == "legacy":
                    response_text = await self._call_legacy_api(image_url, prompt)
                else:
                    response_text = await self._call_openrouter(image_url, prompt)

                response_time = time.time() - request_start_time
                await self.resilient_client.record_success(response_time)
                logger.debug(
                    "%s request successful for %s (%.2fs)", backend_name, image_url, response_time)
                last_exception = None
                break

            except asyncio.TimeoutError as e:
                last_exception = e
                response_time = time.time() - request_start_time
                await self.resilient_client.record_failure(is_timeout=True, response_time_seconds=response_time)
                logger.warning(
                    "Timeout calling %s for %s (attempt %d/%d). timeout=%s, elapsed=%.1fs",
                    backend_name,
                    image_url,
                    attempt + 1,
                    attempts,
                    getattr(config, 'request_timeout', None),
                    response_time,
                )
                await asyncio.sleep(min(30, getattr(config, 'retry_delay', 2.0) * (2 ** attempt)))
                continue

            except Exception as e:
                last_exception = e
                response_time = time.time() - request_start_time
                await self.resilient_client.record_failure(is_timeout=False, response_time_seconds=response_time)
                logger.error(
                    "%s error for %s (attempt %d/%d): %s",
                    backend_name,
                    image_url,
                    attempt + 1,
                    attempts,
                    repr(e),
                )
                if getattr(e, 'retriable', False) and attempt < attempts - 1:
                    await asyncio.sleep(min(30, getattr(config, 'retry_delay', 2.0) * (2 ** attempt)))
                    continue
                break

        if response_text is None:
            stats = self.resilient_client.get_stats()
            logger.error(
                "Exhausted retries calling %s for %s after %d attempts. last_exception=%s, circuit=%s, rate=%.1f/s, queue=%d/%d",
                backend_name,
                image_url,
                attempts,
                repr(last_exception),
                stats['circuit_breaker']['state'],
                stats['rate_limiter']['current_rate'],
                stats['backpressure_queue']['in_flight'],
                stats['backpressure_queue']['max_concurrent'],
            )
            if last_exception:
                raise last_exception
            raise Exception(f"Failed to retrieve {backend_name} response")

        try:
            analysis_data = json.loads(response_text)
        except Exception:
            analysis_data = self._parse_api_response(response_text)
            if analysis_data is None:
                raise Exception(
                    f"Failed to parse {backend_name} response: {response_text}")

        return self._normalize_api_response(analysis_data)

    def _get_next_legacy_endpoint(self) -> str:
        """Get next legacy API endpoint using round-robin load balancing"""
        endpoints = config.legacy_api_endpoints_list
        if not endpoints:
            raise Exception(
                "No legacy API endpoints configured. Set LEGACY_API_ENDPOINTS or LEGACY_API_ENDPOINT.")

        endpoint = endpoints[self._legacy_endpoint_index % len(endpoints)]
        self._legacy_endpoint_index += 1
        return endpoint

    async def _call_legacy_api(self, image_url: str, prompt: str) -> str:
        """Call legacy API endpoint using form data (text prompt + image URL) with load balancing"""

        # Get next endpoint using round-robin
        api_url = self._get_next_legacy_endpoint()
        logger.debug(f"Using legacy endpoint: {api_url}")

        # Prepare form data
        data = aiohttp.FormData()
        data.add_field('text', prompt)
        data.add_field('image_url', image_url)

        # Add API key header if configured
        headers = {}
        if getattr(config, 'legacy_api_key', None):
            headers['Authorization'] = f"Bearer {config.legacy_api_key}"

        async with self.session.post(api_url, data=data, headers=headers, timeout=self._client_timeout) as response:
            if response.status != 200:
                text = await response.text()
                raise Exception(
                    f"Legacy API request failed with status {response.status}: {text[:1000]}")

            response_text = await response.text()

            # Try to parse as JSON first
            try:
                api_response = json.loads(response_text)
            except json.JSONDecodeError:
                # If not JSON, try to extract JSON from markdown
                api_response = self._parse_api_response(response_text)
                if api_response is None:
                    raise Exception(
                        f"Failed to parse legacy API response: {response_text[:500]}")

            # Check for API error responses (status 200 but with error details)
            if 'detail' in api_response and isinstance(api_response['detail'], str):
                if 'invalid' in api_response['detail'].lower() or 'error' in api_response['detail'].lower():
                    raise Exception(
                        f"Legacy API returned error: {api_response['detail']}")

            # Extract the analysis from the response
            if 'response' in api_response:
                # Handle nested response structure
                analysis_text = api_response['response']
                if isinstance(analysis_text, str):
                    # Remove markdown code blocks if present
                    if analysis_text.startswith('```json') and analysis_text.endswith('```'):
                        analysis_text = analysis_text[7:-3].strip()
                    elif analysis_text.startswith('```') and analysis_text.endswith('```'):
                        analysis_text = analysis_text[3:-3].strip()
                    return analysis_text
                else:
                    return json.dumps(analysis_text)
            else:
                # Direct response structure
                return json.dumps(api_response)

    async def _call_openrouter(self, image_url: str, prompt: str) -> str:
        """Call OpenRouter via the OpenAI client (runs in thread to avoid blocking)"""

        # Decide whether to use the preset or explicit model
        model_to_use = getattr(config, 'openrouter_preset', None) or getattr(
            config, 'openrouter_model', 'qwen/qwen-2.5-vl-7b-instruct')

        if self.openai_client:
            payload = f"{prompt}\nImage URL: {image_url}"

            extra_headers = {
                "HTTP-Referer": config.openrouter_referer,
                "X-Title": config.openrouter_site_title,
            }

            # For presets and multimodal models, send a structured content list (text + image)
            messages_payload = [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': image_url}}
                    ]
                }
            ]

            def sync_call():
                return self.openai_client.chat.completions.create(
                    model=model_to_use,
                    messages=messages_payload,
                    temperature=0.0,
                    extra_headers=extra_headers,
                )

            completion = await asyncio.to_thread(sync_call)
        else:
            # Fall back to HTTP POST to OpenRouter if SDK isn't installed but an API key exists
            if not getattr(config, 'openrouter_api_key', None):
                raise Exception(
                    "OpenRouter client unavailable: neither SDK nor OPENROUTER_API_KEY configured")

            # Use multimodal 'image_url' messages for image processing
            body = {
                'model': model_to_use,
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': prompt},
                            {'type': 'image_url', 'image_url': {'url': image_url}}
                        ]
                    }
                ],
                'temperature': 0.0,
            }

            headers = {
                'Authorization': f"Bearer {config.openrouter_api_key}",
                'Content-Type': 'application/json',
            }

            # Include optional extra headers for ranking/site metadata
            extra_headers = {
                'HTTP-Referer': config.openrouter_referer,
                'X-Title': config.openrouter_site_title,
            }
            # Some OpenRouter deployments accept these in a top-level 'extra_headers' key
            body['extra_headers'] = extra_headers

            async with self.session.post('https://openrouter.ai/api/v1/chat/completions', json=body, headers=headers, timeout=self._client_timeout) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(
                        f"OpenRouter HTTP request failed with status {resp.status}: {text[:1000]}")
                completion = await resp.json()

        def _get_field(obj, key):
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        # Try multiple strategies to extract a textual completion from the response.
        # 1) choices[].message.content (string or list)
        if isinstance(completion, dict):
            choices = completion.get('choices')
            if choices:
                first = choices[0]
                # message.content may be a string
                msg = _get_field(first, 'message') or _get_field(
                    first, 'message')
                content = None
                if isinstance(msg, dict):
                    content = msg.get('content')
                # If message.content is a string, return it
                if isinstance(content, str) and content.strip():
                    return content

                # If message.content is a list of blocks (multimodal), join any 'text' fields
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            t = block.get('text') or block.get('content')
                            if isinstance(t, str) and t.strip():
                                parts.append(t.strip())
                        elif isinstance(block, str) and block.strip():
                            parts.append(block.strip())
                    if parts:
                        return '\n'.join(parts)

                # Some responses put raw text at choices[0].text
                text_field = first.get('text')
                if isinstance(text_field, str) and text_field.strip():
                    return text_field

            # 2) data -> content -> list -> text
            data = completion.get('data')
            if isinstance(data, list) and data:
                first = data[0]
                content = first.get('content')
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get('text'):
                            return block.get('text')

            # 3) top-level fields
            for k in ('response', 'text', 'content', 'result'):
                v = completion.get(k)
                if isinstance(v, str) and v.strip():
                    return v
                if isinstance(v, list) and v and isinstance(v[0], str) and v[0].strip():
                    return v[0]

            # 4) as a last resort, if it's dict-like, dump it so parsing later can still happen
            try:
                return json.dumps(completion)
            except Exception:
                pass

        # If it's not a dict, try attribute lookups / fallback
        try:
            # choices attribute
            choices = getattr(completion, 'choices', None)
            if choices:
                first = choices[0]
                msg = getattr(first, 'message', None)
                content = getattr(msg, 'content', None) if msg else None
                if isinstance(content, str) and content.strip():
                    return content
                text_field = getattr(first, 'text', None)
                if isinstance(text_field, str) and text_field.strip():
                    return text_field

            data = getattr(completion, 'data', None)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                content = data[0].get('content')
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get('text'):
                    return content[0].get('text')

        except Exception:
            pass

        raise Exception('Unable to extract OpenRouter completion text')

    def _parse_api_response(self, response_text: str) -> Dict[str, Any]:
        """Parse API response that might be wrapped in markdown"""
        if not response_text or not response_text.strip():
            return None

        # 1) fenced JSON (```json or ```)
        m = re.search(
            r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", response_text, re.DOTALL | re.IGNORECASE)
        if m:
            return json.loads(m.group(1))

        # 2) first inline JSON object/array
        m = re.search(r"(\{.*\}|\[.*\])", response_text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                # continue to other strategies
                pass

        # 3) plain key: value pairs (also supports responses prefixed with 'Final response:')
        #    Example format:
        #    Final response: store_image: true
        #    text_content: "Name", "Tagline", "12345"
        txt = response_text
        m = re.search(r"Final response:\s*(.*)$",
                      response_text, re.IGNORECASE | re.DOTALL)
        if m:
            txt = m.group(1)

        parsed = {}
        for raw_line in txt.splitlines():
            line = raw_line.strip()
            if not line or ':' not in line:
                continue
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip()
            raw_val = val

            # Special handling for known fields
            if key in ('text_content', 'business_contact'):
                # Prefer quoted substrings (keeps commas inside quotes intact)
                quoted = re.findall(r'"([^\"]+)"', raw_val)
                if quoted:
                    parsed[key] = [q.strip() for q in quoted if q.strip()]
                else:
                    # Treat common 'None visible' or 'None' as empty
                    if raw_val.strip().lower() in ('none', 'none visible', 'not visible', 'no', 'n/a'):
                        parsed[key] = []
                    elif ',' in raw_val:
                        items = [v.strip().strip('"').strip("'")
                                 for v in raw_val.split(',') if v.strip()]
                        parsed[key] = items
                    elif raw_val:
                        parsed[key] = [raw_val]
                    else:
                        parsed[key] = []
            elif key == 'store_name':
                # If multiple quoted names present, join them into a single string separated by '; '
                quoted = re.findall(r'"([^\"]+)"', raw_val)
                if quoted:
                    if len(quoted) == 1:
                        parsed[key] = quoted[0].strip()
                    else:
                        parsed[key] = '; '.join(q.strip()
                                                for q in quoted if q.strip())
                else:
                    # fallback: remove surrounding quotes if present
                    if (raw_val.startswith('"') and raw_val.endswith('"')) or (raw_val.startswith("'") and raw_val.endswith("'")):
                        parsed[key] = raw_val[1:-1].strip()
                    else:
                        parsed[key] = raw_val
            else:
                parsed[key] = val

        if parsed:
            return parsed

        # 4) last resort: try parsing entire response as JSON
        return json.loads(response_text)

    def _normalize_api_response(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize API response to expected format"""
        # Ensure all expected fields are present with defaults
        normalized = {
            'store_image': api_data.get('store_image', False),
            'text_content': api_data.get('text_content', []),
            'store_name': api_data.get('store_name', ''),
            'business_contact': api_data.get('business_contact', []),
            'image_description': api_data.get('image_description', ''),
            'phone_number': False
        }

        # Ensure text_content is a list; split comma-separated strings if present
        if isinstance(normalized['text_content'], str):
            if ',' in normalized['text_content']:
                normalized['text_content'] = [t.strip().strip('"').strip(
                    "'") for t in normalized['text_content'].split(',') if t.strip()]
            else:
                normalized['text_content'] = [normalized['text_content']]
        elif not isinstance(normalized['text_content'], list):
            normalized['text_content'] = []

        # Ensure business_contact is a list; split comma-separated strings if present
        if isinstance(normalized['business_contact'], str):
            if ',' in normalized['business_contact']:
                normalized['business_contact'] = [t.strip().strip('"').strip(
                    "'") for t in normalized['business_contact'].split(',') if t.strip()]
            else:
                normalized['business_contact'] = [
                    normalized['business_contact']]
        elif not isinstance(normalized['business_contact'], list):
            normalized['business_contact'] = []

        # First handle "no contact" cases before phone number detection
        # Common phrases that indicate no contact information
        no_contact_phrases = {
            'no result', 'no phone number visible', 'no phone number', 'no contact',
            'not visible', 'none visible', 'none', 'n/a', 'na', 'no', 'null'
        }

        should_set_no_contact = False

        # Check text_content for no-contact indicators
        try:
            text_items = [t.strip() for t in normalized.get(
                'text_content', []) if isinstance(t, str) and t.strip()]
        except Exception:
            text_items = []

        for t in text_items:
            if t.lower() in no_contact_phrases:
                should_set_no_contact = True
                break

        # Check business_contact for no-contact indicators or empty/null values
        try:
            contact_items = [c.strip() for c in normalized.get(
                'business_contact', []) if isinstance(c, str) and c.strip()]
        except Exception:
            contact_items = []

        # If business_contact is empty or contains only no-contact phrases
        if not contact_items:
            should_set_no_contact = True
        else:
            # Be permissive: consider substring matches and ignore punctuation
            for c in contact_items:
                lc = re.sub(r"[^a-z0-9\s+]", "", c.lower()).strip()
                for phrase in no_contact_phrases:
                    if phrase in lc:
                        should_set_no_contact = True
                        break
                if should_set_no_contact:
                    break

        if should_set_no_contact:
            normalized['business_contact'] = ['no']
            normalized['phone_number'] = False
        else:
            # Only check for phone numbers if we don't have a "no contact" case
            # Set phone_number if any contact looks like a phone number (digits, optional +, spaces, dashes)
            phone_re = re.compile(r"\+?\d[\d\s\-()]{5,}\d$")
            found_phone = False
            for contact in normalized['business_contact']:
                if isinstance(contact, str) and phone_re.search(contact.strip()):
                    found_phone = True
                    break
            # Also search text_content for phone-like tokens
            if not found_phone:
                for txt in normalized['text_content']:
                    if isinstance(txt, str) and phone_re.search(txt.strip()):
                        found_phone = True
                        break

            normalized['phone_number'] = found_phone

        # Coerce store_image to boolean (accept 'true'/'false' strings)
        si = normalized.get('store_image')
        if isinstance(si, str):
            normalized['store_image'] = si.strip(
            ).lower() in ('true', '1', 'yes')
        else:
            normalized['store_image'] = bool(si)

        return normalized

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL(for caching, non-security use)"""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


# Global instance for easy access
image_processor = ImageProcessor()
