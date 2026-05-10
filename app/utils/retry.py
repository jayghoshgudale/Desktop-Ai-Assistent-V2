import logging
import time
from typing import Callable, TypeVar

logger = logging.getLogger("J.A.R.V.I.S")

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> T:
    """Execute callable with exponential backoff retries."""
    last_exception = None
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_exception = e
            if attempt == max_retries - 1:
                raise

            logger.warning(
                "Attempt %s/%s failed (%s). Retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                getattr(fn, "__name__", "call"),
                delay,
                e,
            )
            time.sleep(delay)
            delay *= 2  # Exponential backoff: 1s, 2s, 4s, ...

    raise last_exception
