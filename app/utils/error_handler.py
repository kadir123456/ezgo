import asyncio
import time
from typing import Callable, Any
from functools import wraps
import logging

logger = logging.getLogger("error_handler")

class CircuitBreakerError(Exception):
    """Circuit breaker açık olduğunda fırlatılan hata"""
    pass

class CircuitBreaker:
    """Simple circuit breaker pattern"""
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    async def call(self, func: Callable, *args, **kwargs):
        """Circuit breaker ile fonksiyon çağrısı"""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerError("Circuit breaker is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _should_attempt_reset(self) -> bool:
        """Circuit breaker'ı reset etmeyi deneyip denemeyeceğini kontrol eder"""
        return (
            self.last_failure_time and 
            time.time() - self.last_failure_time >= self.timeout
        )

    def _on_success(self):
        """Başarılı çağrı sonrası state güncelleme"""
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        """Başarısız çağrı sonrası state güncelleme"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker opened: {self.failure_count} failures")

# Global circuit breaker instances
binance_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=30)
firebase_circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)

def robust_binance_call(max_attempts: int = 3):
    """Binance API çağrıları için robust decorator"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await binance_circuit_breaker.call(func, *args, **kwargs)
                except CircuitBreakerError:
                    logger.error("Binance circuit breaker is open")
                    raise Exception("Service temporarily unavailable")
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"Binance call failed after {max_attempts} attempts: {e}")
                        raise
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
            return None
        return wrapper
    return decorator

def robust_firebase_call(max_attempts: int = 2):
    """Firebase çağrıları için robust decorator"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await firebase_circuit_breaker.call(func, *args, **kwargs)
                except CircuitBreakerError:
                    logger.error("Firebase circuit breaker is open")
                    raise Exception("Database temporarily unavailable")
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"Firebase call failed: {e}")
                        raise
                    await asyncio.sleep(1)
            return None
        return wrapper
    return decorator

async def safe_async_call(func: Callable, *args, default_return=None, **kwargs):
    """Güvenli async fonksiyon çağrısı"""
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        logger.error(f"Safe async call failed: {func.__name__}: {e}")
        return default_return
