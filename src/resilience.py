"""
Resilience patterns for high-throughput API processing

Implements:
1. Backpressure Queue - Limits concurrent requests to prevent overwhelming the API
2. Adaptive Rate Limiter - Dynamically adjusts request rate based on API response times
3. Circuit Breaker - Stops requests when API is overwhelmed or failing

These patterns work together to ensure the system can handle millions of URLs
without causing timeouts or overwhelming the backend model.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any, Deque
from collections import deque
import statistics

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"       # Normal operation, requests allowed
    OPEN = "open"           # Circuit tripped, requests blocked
    HALF_OPEN = "half_open" # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 10           # Failures before opening circuit
    success_threshold: int = 3            # Successes needed to close circuit
    timeout_seconds: float = 60.0         # Time before attempting recovery
    half_open_max_requests: int = 3       # Max requests in half-open state
    
    # Timeout-specific thresholds
    timeout_failure_weight: float = 2.0   # Timeouts count as multiple failures
    slow_call_threshold_ms: float = 30000 # Calls > 30s are considered slow
    slow_call_failure_weight: float = 0.5 # Slow calls partially count as failures


@dataclass
class AdaptiveRateLimiterConfig:
    """Configuration for adaptive rate limiter"""
    initial_rate: float = 20.0            # Initial requests per second (increased for A100)
    min_rate: float = 8.0                 # Minimum requests per second (increased - GPUs are fast)
    max_rate: float = 50.0                # Maximum requests per second
    
    # Response time thresholds (milliseconds) - tuned for fast A100 GPUs
    target_response_time_ms: float = 3000    # Target: 3 seconds (A100 is fast)
    slow_threshold_ms: float = 30000         # Slow: > 30 seconds (increased tolerance)
    critical_threshold_ms: float = 90000     # Critical: > 90 seconds (increased tolerance)
    
    # Rate adjustment factors - less aggressive to maintain stability
    increase_factor: float = 1.15         # Rate increase when fast (15%)
    decrease_factor: float = 0.85         # Rate decrease when slow (15% drop, not 30%)
    critical_decrease_factor: float = 0.6 # Rate decrease when critical (40% drop, not 60%)
    
    # Measurement window - larger for more stability
    window_size: int = 100                # Number of samples for averaging (increased)
    adjustment_interval: float = 10.0     # Seconds between rate adjustments (slower)


@dataclass
class BackpressureQueueConfig:
    """Configuration for backpressure queue"""
    max_concurrent: int = 8               # Max concurrent in-flight requests
    max_queue_size: int = 1000            # Max queued requests before rejecting
    queue_timeout: float = 300.0          # Max time a request can wait in queue
    
    # Backpressure signals
    high_watermark: float = 0.8           # Start slowing at 80% capacity
    low_watermark: float = 0.5            # Resume normal at 50% capacity


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    Prevents cascading failures by stopping requests when the API
    is overwhelmed or failing consistently.
    """
    
    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_requests = 0
        self._lock = asyncio.Lock()
        
        # Metrics
        self._total_requests = 0
        self._total_failures = 0
        self._total_timeouts = 0
        self._state_changes = 0
        
        logger.info(f"CircuitBreaker '{name}' initialized: failure_threshold={self.config.failure_threshold}")
    
    @property
    def state(self) -> CircuitState:
        return self._state
    
    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN
    
    async def can_execute(self) -> bool:
        """Check if a request can be executed"""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            
            if self._state == CircuitState.OPEN:
                # Check if timeout has elapsed
                if self._last_failure_time:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.config.timeout_seconds:
                        self._transition_to_half_open()
                        return True
                return False
            
            if self._state == CircuitState.HALF_OPEN:
                # In half-open state, allow ALL requests through for testing
                # We'll close the circuit based on success/failure rates
                # This prevents rejecting good requests while testing recovery
                self._half_open_requests += 1
                return True
            
            return False
    
    async def record_success(self, response_time_ms: float = 0):
        """Record a successful request"""
        async with self._lock:
            self._total_requests += 1
            
            # Check if it was a slow call
            is_slow = response_time_ms > self.config.slow_call_threshold_ms
            
            if self._state == CircuitState.HALF_OPEN:
                if is_slow:
                    # Slow calls in half-open don't count as full success
                    logger.debug(f"CircuitBreaker '{self.name}': slow call in half-open ({response_time_ms:.0f}ms)")
                else:
                    self._success_count += 1
                    if self._success_count >= self.config.success_threshold:
                        self._transition_to_closed()
            
            elif self._state == CircuitState.CLOSED:
                # Successful requests reset failure count (with decay)
                if not is_slow:
                    self._failure_count = max(0, self._failure_count - 0.5)
    
    async def record_failure(self, is_timeout: bool = False, response_time_ms: float = 0):
        """Record a failed request"""
        async with self._lock:
            self._total_requests += 1
            self._total_failures += 1
            if is_timeout:
                self._total_timeouts += 1
            
            # Calculate failure weight
            weight = 1.0
            if is_timeout:
                weight = self.config.timeout_failure_weight
            elif response_time_ms > self.config.slow_call_threshold_ms:
                weight = self.config.slow_call_failure_weight
            
            self._failure_count += weight
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # In half-open, track failures but don't immediately reopen
                # Only reopen if we get multiple consecutive failures
                if self._failure_count >= self.config.failure_threshold / 2:
                    self._transition_to_open()
            
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to_open()
    
    def _transition_to_open(self):
        """Transition to OPEN state"""
        prev_state = self._state
        self._state = CircuitState.OPEN
        self._state_changes += 1
        self._success_count = 0
        self._half_open_requests = 0
        logger.warning(
            f"CircuitBreaker '{self.name}': {prev_state.value} -> OPEN "
            f"(failures={self._failure_count:.1f}, timeouts={self._total_timeouts})"
        )
    
    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        self._state = CircuitState.HALF_OPEN
        self._state_changes += 1
        self._half_open_requests = 0
        self._success_count = 0
        logger.info(f"CircuitBreaker '{self.name}': OPEN -> HALF_OPEN (testing recovery)")
    
    def _transition_to_closed(self):
        """Transition to CLOSED state"""
        self._state = CircuitState.CLOSED
        self._state_changes += 1
        self._failure_count = 0
        self._success_count = 0
        self._half_open_requests = 0
        logger.info(f"CircuitBreaker '{self.name}': HALF_OPEN -> CLOSED (recovered)")
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics"""
        return {
            'name': self.name,
            'state': self._state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'total_requests': self._total_requests,
            'total_failures': self._total_failures,
            'total_timeouts': self._total_timeouts,
            'state_changes': self._state_changes,
        }
    
    async def reset(self):
        """Reset circuit breaker to closed state"""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_requests = 0
            logger.info(f"CircuitBreaker '{self.name}': manually reset to CLOSED")


class AdaptiveRateLimiter:
    """
    Adaptive rate limiter that adjusts throughput based on API response times.
    
    When API responses are fast, increases rate.
    When API responses are slow, decreases rate.
    When API is overwhelmed, dramatically reduces rate.
    """
    
    def __init__(self, config: AdaptiveRateLimiterConfig = None):
        self.config = config or AdaptiveRateLimiterConfig()
        
        self._current_rate = self.config.initial_rate
        self._response_times: Deque[float] = deque(maxlen=self.config.window_size)
        self._last_adjustment = time.time()
        self._lock = asyncio.Lock()
        
        # Token bucket for rate limiting
        self._tokens = self._current_rate
        self._last_token_update = time.time()
        self._token_lock = asyncio.Lock()
        
        # Metrics
        self._total_requests = 0
        self._total_wait_time = 0.0
        self._rate_adjustments = 0
        
        logger.info(
            f"AdaptiveRateLimiter initialized: rate={self._current_rate:.1f}/s, "
            f"target_response={self.config.target_response_time_ms}ms"
        )
    
    @property
    def current_rate(self) -> float:
        return self._current_rate
    
    async def acquire(self, timeout: float = 60.0) -> bool:
        """
        Acquire permission to make a request.
        Returns True if acquired, False if timed out.
        """
        start_wait = time.time()
        deadline = start_wait + timeout
        
        while True:
            async with self._token_lock:
                # Refill tokens based on elapsed time
                now = time.time()
                elapsed = now - self._last_token_update
                self._tokens = min(
                    self._current_rate,  # Max burst = current rate
                    self._tokens + elapsed * self._current_rate
                )
                self._last_token_update = now
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    wait_time = now - start_wait
                    self._total_wait_time += wait_time
                    if wait_time > 1.0:
                        logger.debug(f"Rate limiter wait: {wait_time:.2f}s")
                    return True
            
            # Check timeout
            if time.time() >= deadline:
                return False
            
            # Wait for tokens to refill
            wait_time = 1.0 / max(1.0, self._current_rate)
            await asyncio.sleep(min(wait_time, deadline - time.time()))
    
    async def record_response_time(self, response_time_ms: float):
        """Record a response time for rate adjustment"""
        async with self._lock:
            self._response_times.append(response_time_ms)
            
            # Check if we should adjust rate
            now = time.time()
            if now - self._last_adjustment >= self.config.adjustment_interval:
                await self._adjust_rate()
                self._last_adjustment = now
    
    async def _adjust_rate(self):
        """Adjust rate based on recent response times"""
        if len(self._response_times) < 5:
            return  # Not enough samples
        
        # Calculate statistics
        avg_response = statistics.mean(self._response_times)
        p95_response = sorted(self._response_times)[int(len(self._response_times) * 0.95)]
        
        old_rate = self._current_rate
        
        if p95_response > self.config.critical_threshold_ms:
            # Critical: dramatically reduce rate
            self._current_rate *= self.config.critical_decrease_factor
            reason = f"CRITICAL (p95={p95_response:.0f}ms)"
        
        elif avg_response > self.config.slow_threshold_ms:
            # Slow: reduce rate
            self._current_rate *= self.config.decrease_factor
            reason = f"SLOW (avg={avg_response:.0f}ms)"
        
        elif avg_response < self.config.target_response_time_ms:
            # Fast: increase rate
            self._current_rate *= self.config.increase_factor
            reason = f"FAST (avg={avg_response:.0f}ms)"
        
        else:
            # Normal: slight adjustment toward target
            reason = None
        
        # Apply bounds
        self._current_rate = max(
            self.config.min_rate,
            min(self.config.max_rate, self._current_rate)
        )
        
        if reason and abs(old_rate - self._current_rate) > 0.1:
            self._rate_adjustments += 1
            logger.info(
                f"Rate adjusted: {old_rate:.1f} -> {self._current_rate:.1f}/s ({reason})"
            )
    
    async def force_reduce_rate(self, factor: float = 0.5):
        """Force reduce rate (called on errors/timeouts)"""
        async with self._lock:
            old_rate = self._current_rate
            self._current_rate = max(
                self.config.min_rate,
                self._current_rate * factor
            )
            logger.warning(f"Rate force-reduced: {old_rate:.1f} -> {self._current_rate:.1f}/s")
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics"""
        avg_response = statistics.mean(self._response_times) if self._response_times else 0
        avg_wait = self._total_wait_time / max(1, self._total_requests)
        
        return {
            'current_rate': self._current_rate,
            'avg_response_ms': avg_response,
            'total_requests': self._total_requests,
            'avg_wait_time': avg_wait,
            'rate_adjustments': self._rate_adjustments,
            'sample_count': len(self._response_times),
        }


class BackpressureQueue:
    """
    Backpressure queue that limits concurrent in-flight requests.
    
    Prevents overwhelming the API by:
    1. Limiting concurrent requests to a configurable maximum
    2. Queueing excess requests with timeout
    3. Providing backpressure signals when queue is filling up
    """
    
    def __init__(self, config: BackpressureQueueConfig = None):
        self.config = config or BackpressureQueueConfig()
        
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._in_flight = 0
        self._queue_size = 0
        self._lock = asyncio.Lock()
        
        # Metrics
        self._total_acquired = 0
        self._total_rejected = 0
        self._total_timeouts = 0
        self._max_queue_observed = 0
        self._max_inflight_observed = 0
        
        logger.info(
            f"BackpressureQueue initialized: max_concurrent={self.config.max_concurrent}, "
            f"max_queue={self.config.max_queue_size}"
        )
    
    @property
    def in_flight(self) -> int:
        return self._in_flight
    
    @property
    def queue_size(self) -> int:
        return self._queue_size
    
    @property
    def utilization(self) -> float:
        """Current utilization as fraction of max concurrent"""
        return self._in_flight / self.config.max_concurrent
    
    @property
    def is_under_pressure(self) -> bool:
        """Check if queue is experiencing backpressure"""
        return self.utilization >= self.config.high_watermark
    
    async def acquire(self, timeout: float = None) -> bool:
        """
        Acquire a slot for executing a request.
        Returns True if acquired, False if rejected or timed out.
        """
        timeout = timeout or self.config.queue_timeout
        
        async with self._lock:
            # Check if queue is full
            if self._queue_size >= self.config.max_queue_size:
                self._total_rejected += 1
                logger.warning(
                    f"BackpressureQueue: rejecting request (queue full: {self._queue_size})"
                )
                return False
            
            self._queue_size += 1
            self._max_queue_observed = max(self._max_queue_observed, self._queue_size)
        
        try:
            # Wait for semaphore with timeout
            acquired = await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=timeout
            )
            
            if acquired:
                async with self._lock:
                    self._queue_size -= 1
                    self._in_flight += 1
                    self._total_acquired += 1
                    self._max_inflight_observed = max(self._max_inflight_observed, self._in_flight)
                return True
            
            return False
            
        except asyncio.TimeoutError:
            async with self._lock:
                self._queue_size -= 1
                self._total_timeouts += 1
            logger.warning(f"BackpressureQueue: request timed out waiting in queue")
            return False
    
    async def release(self):
        """Release a slot after request completion"""
        async with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
        self._semaphore.release()
    
    async def adjust_concurrency(self, new_max: int):
        """Dynamically adjust max concurrent requests"""
        async with self._lock:
            old_max = self.config.max_concurrent
            self.config.max_concurrent = max(1, new_max)
            
            # Adjust semaphore
            diff = new_max - old_max
            if diff > 0:
                # Increase capacity
                for _ in range(diff):
                    self._semaphore.release()
            # Note: decreasing capacity is handled naturally by not releasing
            
            logger.info(f"BackpressureQueue: concurrency adjusted {old_max} -> {new_max}")
    
    def get_stats(self) -> dict:
        """Get queue statistics"""
        return {
            'in_flight': self._in_flight,
            'queue_size': self._queue_size,
            'max_concurrent': self.config.max_concurrent,
            'utilization': self.utilization,
            'is_under_pressure': self.is_under_pressure,
            'total_acquired': self._total_acquired,
            'total_rejected': self._total_rejected,
            'total_timeouts': self._total_timeouts,
            'max_queue_observed': self._max_queue_observed,
            'max_inflight_observed': self._max_inflight_observed,
        }


class ResilientAPIClient:
    """
    Combines all resilience patterns into a unified API client wrapper.
    
    Usage:
        client = ResilientAPIClient()
        
        async with client.request_context() as can_proceed:
            if can_proceed:
                start = time.time()
                result = await make_api_call()
                await client.record_success(time.time() - start)
            else:
                # Handle rejection
    """
    
    def __init__(
        self,
        circuit_config: CircuitBreakerConfig = None,
        rate_config: AdaptiveRateLimiterConfig = None,
        queue_config: BackpressureQueueConfig = None,
        name: str = "api"
    ):
        self.name = name
        self.circuit_breaker = CircuitBreaker(f"{name}_circuit", circuit_config)
        self.rate_limiter = AdaptiveRateLimiter(rate_config)
        self.backpressure_queue = BackpressureQueue(queue_config)
        
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._rejected_requests = 0
        
        logger.info(f"ResilientAPIClient '{name}' initialized with all resilience patterns")
    
    async def can_proceed(self) -> bool:
        """
        Check if a request can proceed through all gates.
        Does NOT acquire resources - use request_context() for that.
        """
        # Check circuit breaker first (fast fail)
        if not await self.circuit_breaker.can_execute():
            return False
        
        # Check if under severe backpressure
        if self.backpressure_queue.queue_size >= self.backpressure_queue.config.max_queue_size * 0.9:
            return False
        
        return True
    
    async def acquire(self, timeout: float = 120.0) -> bool:
        """
        Acquire permission to make a request.
        Goes through all gates: circuit breaker -> rate limiter -> backpressure queue
        """
        self._total_requests += 1
        
        # Gate 1: Circuit breaker
        if not await self.circuit_breaker.can_execute():
            self._rejected_requests += 1
            logger.debug(f"Request rejected by circuit breaker (state={self.circuit_breaker.state.value})")
            return False
        
        # Gate 2: Rate limiter
        if not await self.rate_limiter.acquire(timeout=timeout / 2):
            self._rejected_requests += 1
            logger.debug("Request rejected by rate limiter (timeout)")
            return False
        
        # Gate 3: Backpressure queue
        if not await self.backpressure_queue.acquire(timeout=timeout / 2):
            self._rejected_requests += 1
            logger.debug("Request rejected by backpressure queue")
            return False
        
        return True
    
    async def release(self):
        """Release resources after request completion"""
        await self.backpressure_queue.release()
    
    async def record_success(self, response_time_seconds: float):
        """Record successful request"""
        response_time_ms = response_time_seconds * 1000
        self._successful_requests += 1
        
        await self.circuit_breaker.record_success(response_time_ms)
        await self.rate_limiter.record_response_time(response_time_ms)
        
        # If response was slow, also reduce rate slightly
        if response_time_ms > self.rate_limiter.config.slow_threshold_ms:
            await self.rate_limiter.force_reduce_rate(0.9)
    
    async def record_failure(self, is_timeout: bool = False, response_time_seconds: float = 0):
        """Record failed request"""
        response_time_ms = response_time_seconds * 1000
        self._failed_requests += 1
        
        await self.circuit_breaker.record_failure(is_timeout, response_time_ms)
        
        # Force reduce rate on failures
        if is_timeout:
            await self.rate_limiter.force_reduce_rate(0.5)
        else:
            await self.rate_limiter.force_reduce_rate(0.7)
    
    def get_stats(self) -> dict:
        """Get comprehensive statistics"""
        return {
            'name': self.name,
            'total_requests': self._total_requests,
            'successful_requests': self._successful_requests,
            'failed_requests': self._failed_requests,
            'rejected_requests': self._rejected_requests,
            'success_rate': self._successful_requests / max(1, self._total_requests - self._rejected_requests),
            'circuit_breaker': self.circuit_breaker.get_stats(),
            'rate_limiter': self.rate_limiter.get_stats(),
            'backpressure_queue': self.backpressure_queue.get_stats(),
        }
    
    async def reset(self):
        """Reset all patterns to initial state"""
        await self.circuit_breaker.reset()
        logger.info(f"ResilientAPIClient '{self.name}' reset")


# Global instance with default configuration optimized for the LLM model
_default_resilient_client: Optional[ResilientAPIClient] = None


def get_resilient_client() -> ResilientAPIClient:
    """Get or create the default resilient client"""
    global _default_resilient_client
    import os
    
    if _default_resilient_client is None:
        # Load configuration from environment variables with sensible defaults
        # Tuned for Qwen VL model which takes 3-10 seconds per image
        
        circuit_config = CircuitBreakerConfig(
            failure_threshold=int(os.getenv('CIRCUIT_FAILURE_THRESHOLD', '50')),  # Increased
            success_threshold=int(os.getenv('CIRCUIT_SUCCESS_THRESHOLD', '3')),
            timeout_seconds=float(os.getenv('CIRCUIT_TIMEOUT_SECONDS', '30')),  # Faster recovery
            half_open_max_requests=int(os.getenv('CIRCUIT_HALF_OPEN_MAX', '100')),  # Allow many in half-open
            timeout_failure_weight=float(os.getenv('TIMEOUT_FAILURE_WEIGHT', '1.5')),  # Less aggressive
            slow_call_threshold_ms=float(os.getenv('SLOW_CALL_THRESHOLD_MS', '60000')),  # 1 minute
        )
        
        rate_config = AdaptiveRateLimiterConfig(
            initial_rate=float(os.getenv('RESILIENCE_INITIAL_RATE', '20.0')),
            min_rate=float(os.getenv('RESILIENCE_MIN_RATE', '8.0')),
            max_rate=float(os.getenv('RESILIENCE_MAX_RATE', '50.0')),
            target_response_time_ms=float(os.getenv('TARGET_RESPONSE_TIME_MS', '3000')),  # 3s target for A100
            slow_threshold_ms=float(os.getenv('SLOW_THRESHOLD_MS', '30000')),  # 30s slow
            critical_threshold_ms=float(os.getenv('CRITICAL_THRESHOLD_MS', '90000')),  # 90s critical
            window_size=int(os.getenv('RATE_WINDOW_SIZE', '100')),
            adjustment_interval=float(os.getenv('RATE_ADJUSTMENT_INTERVAL', '10.0')),
            increase_factor=float(os.getenv('RATE_INCREASE_FACTOR', '1.15')),
            decrease_factor=float(os.getenv('RATE_DECREASE_FACTOR', '0.85')),
            critical_decrease_factor=float(os.getenv('RATE_CRITICAL_DECREASE_FACTOR', '0.6')),
        )
        
        queue_config = BackpressureQueueConfig(
            max_concurrent=int(os.getenv('RESILIENCE_MAX_CONCURRENT', '16')),  # Higher default
            max_queue_size=int(os.getenv('RESILIENCE_MAX_QUEUE', '1000')),
            queue_timeout=float(os.getenv('QUEUE_TIMEOUT', '300.0')),  # 5 min queue timeout
            high_watermark=float(os.getenv('QUEUE_HIGH_WATERMARK', '0.85')),
            low_watermark=float(os.getenv('QUEUE_LOW_WATERMARK', '0.5')),
        )
        
        _default_resilient_client = ResilientAPIClient(
            circuit_config=circuit_config,
            rate_config=rate_config,
            queue_config=queue_config,
            name="llm_api"
        )
    
    return _default_resilient_client


def reset_resilient_client():
    """Reset the global resilient client (for testing)"""
    global _default_resilient_client
    _default_resilient_client = None
