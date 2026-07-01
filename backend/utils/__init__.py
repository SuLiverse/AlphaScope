"""Backend utility modules."""
import logging
from typing import Any, Callable, Optional

_logger = logging.getLogger(__name__)


def safe_call(fn: Callable, *args: Any, **kwargs: Any) -> Optional[Any]:
    """Call *fn* and return its result, or *None* on failure with a debug log.

    Replaces the duplicated ``_safe()`` helpers across news_data, fund_flow,
    fundamentals, and providers.  Unlike the originals which silently swallowed
    all exceptions, this version logs at DEBUG level so failures are traceable.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        _logger.debug("safe_call: %s raised %s: %s", getattr(fn, "__name__", fn), type(e).__name__, e)
        return None

