"""Wrap a logging handler and count records it drops because of errors.

The wrapped handler is called first. If it raises, the record is counted as
lost and the exception is swallowed (unless ``raise_on_error`` is set). When
the lost count reaches ``flush_every``, a summary record is emitted through
the *same* wrapped handler so the accounting stays inside whatever sink the
caller already configured.

Design choice: the summary record is delivered with ``handler.handle`` rather
than ``logging.Logger.handle``. That keeps the counter independent of any
particular logger and avoids recursion through the root logger. The summary
carries the lost count in ``record.lost_count`` and its ``msg`` is the literal
format string ``"%d log records lost"`` so that a formatter can render it.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional


class CountingHandlerAdapter(logging.Handler):
    """A logging handler that forwards to another handler and counts losses.

    Parameters
    ----------
    wrapped:
        The handler that actually writes records. It is called synchronously
        from :meth:`emit`.
    flush_every:
        Emit a summary record after this many lost records. Must be positive.
        A value of ``0`` disables flushing entirely (useful when the caller
        wants to read the count themselves).
    raise_on_error:
        When true, exceptions from ``wrapped`` are re-raised after being
        counted. Defaults to false so a single bad record does not kill the
        emitting thread.
    """

    def __init__(
        self,
        wrapped: logging.Handler,
        flush_every: int = 100,
        raise_on_error: bool = False,
    ) -> None:
        super().__init__()
        if flush_every < 0:
            raise ValueError("flush_every must be >= 0")
        self._wrapped = wrapped
        self._flush_every = flush_every
        self._raise_on_error = raise_on_error
        self._lost = 0
        self._emitted = 0
        # A plain Lock is enough: the critical sections are tiny and never
        # call back into user code while held, except for the summary emit
        # which we do after releasing the lock to avoid deadlock when the
        # wrapped handler itself logs.
        self._lock = threading.Lock()

    @property
    def wrapped(self) -> logging.Handler:
        """The handler that receives forwarded records."""
        return self._wrapped

    @property
    def lost_count(self) -> int:
        """Number of records dropped so far since construction or reset."""
        with self._lock:
            return self._lost

    @property
    def emitted_count(self) -> int:
        """Number of records successfully forwarded to the wrapped handler."""
        with self._lock:
            return self._emitted

    def reset(self) -> None:
        """Zero both counters. Does not touch the wrapped handler."""
        with self._lock:
            self._lost = 0
            self._emitted = 0

    def emit(self, record: logging.LogRecord) -> None:
        """Forward ``record``; count and optionally re-raise on failure."""
        try:
            self._wrapped.emit(record)
        except Exception:
            should_flush = self._record_loss()
            if should_flush:
                self._flush_summary()
            if self._raise_on_error:
                raise
        else:
            with self._lock:
                self._emitted += 1

    def _record_loss(self) -> bool:
        """Increment the loss counter; return True when a flush is due."""
        with self._lock:
            self._lost += 1
            if self._flush_every == 0:
                return False
            return self._lost % self._flush_every == 0

    def _flush_summary(self) -> None:
        """Emit a summary record through the wrapped handler.

        Any error here is swallowed: a broken sink must not turn a counting
        wrapper into a source of further errors. The count is captured before
        emitting so the summary reflects the moment of the flush even if the
        wrapped handler logs during its own emit.
        """
        with self._lock:
            lost = self._lost
        summary = logging.LogRecord(
            name="log_record_loss_counter",
            level=logging.WARNING,
            pathname=__file__,
            lineno=0,
            msg="%d log records lost",
            args=(lost,),
            exc_info=None,
        )
        # Attach the raw count so formatters can use it without parsing msg.
        summary.lost_count = lost  # type: ignore[attr-defined]
        try:
            self._wrapped.emit(summary)
        except Exception:
            pass

    def close(self) -> None:
        """Close the wrapped handler and this adapter."""
        try:
            self._wrapped.close()
        finally:
            super().close()


class LossCountingHandler(CountingHandlerAdapter):
    """Backwards-friendly alias with the same behaviour.

    Kept as a distinct name so callers can pick whichever reads better at the
    call site; both classes are interchangeable.
    """

    def __init__(
        self,
        wrapped: Optional[logging.Handler] = None,
        flush_every: int = 100,
        raise_on_error: bool = False,
    ) -> None:
        if wrapped is None:
            wrapped = logging.NullHandler()
        super().__init__(
            wrapped=wrapped,
            flush_every=flush_every,
            raise_on_error=raise_on_error,
        )
