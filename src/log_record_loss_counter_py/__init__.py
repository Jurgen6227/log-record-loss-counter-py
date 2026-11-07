"""Log Record Loss Counter public API.

Re-exports the small surface area of the package so callers can do::

    from log_record_loss_counter_py import LossCountingHandler
"""

from .core import LossCountingHandler, CountingHandlerAdapter

__all__ = ["LossCountingHandler", "CountingHandlerAdapter"]
