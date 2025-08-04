"""
Backoff retry decorator for handling transient failures in the Treasury Bills Calculator.
مزخرف إعادة المحاولة التدريجية لمعالجة الأخطاء المؤقتة في حاسبة أذون الخزانة.
"""

import logging
import time
import random
from typing import TypeVar, Callable, Any, Dict, Optional
from functools import wraps

T = TypeVar("T")

logger = logging.getLogger(__name__)


def backoff_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions_to_catch: tuple = (Exception,),
    retry_conditions: Optional[Callable[[Exception], bool]] = None,
    on_retry_callback: Optional[Callable[[int, float, Exception], None]] = None,
):
    """
    Decorator for exponential backoff retry with jitter and custom conditions.
    مزخرف للتنفيذ بإعادة المحاولة التدريجية للدوال مع دعم الجيتر والشروط المخصصة.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds between attempts (will double with each attempt)
        max_delay: Maximum delay between attempts
        jitter: Add randomness to avoid multiple simultaneous requests
        exceptions_to_catch: Types of exceptions to retry on
        retry_conditions: Function that accepts exception and returns True if should retry
        on_retry_callback: Function called before each retry with attempt number, delay, and exception
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Dict[str, Any]) -> T:
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions_to_catch as e:
                    retries += 1

                    # Check if retry is allowed based on conditions
                    if retry_conditions and not retry_conditions(e):
                        logger.error(f"لا يمكن إعادة المحاولة وفقًا للشروط: {str(e)}")
                        raise

                    # Check remaining attempts
                    if retries > max_retries:
                        logger.error(
                            f"تم استنفاذ عدد المحاولات ({max_retries}). الاستثناء الأخير: {str(e)}"
                        )
                        raise

                    # Calculate exponential delay with jitter
                    delay = min(base_delay * (2 ** (retries - 1)), max_delay)
                    if jitter:
                        # Add up to 25% randomness
                        delay = delay * (1 + random.uniform(0, 0.25))

                    # Execute callback function if specified
                    if on_retry_callback:
                        on_retry_callback(retries, delay, e)

                    logger.warning(
                        f"محاولة {retries}/{max_retries} فشلت، إعادة المحاولة بعد {delay:.2f} ثانية. السبب: {str(e)}"
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
