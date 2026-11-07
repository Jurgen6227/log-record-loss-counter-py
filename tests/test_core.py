"""Tests for the loss counting handler.

Everything here is deterministic: no clocks, no sleeps, no real I/O. The
"wrapped" handler is a tiny in-memory recorder defined in this file.
"""

import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from log_record_loss_counter_py import (  # noqa: E402
    CountingHandlerAdapter,
    LossCountingHandler,
)


class RecordingHandler(logging.Handler):
    """Collects records in a list; optionally raises on chosen records."""

    def __init__(self, fail_predicate=None):
        super().__init__()
        self.records = []
        self.fail_predicate = fail_predicate

    def emit(self, record):
        if self.fail_predicate is not None and self.fail_predicate(record):
            raise RuntimeError("sink failure")
        self.records.append(record)


class AlwaysFailingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def emit(self, record):
        self.calls += 1
        raise ValueError("nope")


def make_record(msg="hello", level=logging.INFO):
    return logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


class CountingHandlerAdapterTests(unittest.TestCase):
    def test_successful_records_are_forwarded_and_counted(self):
        sink = RecordingHandler()
        adapter = CountingHandlerAdapter(sink)
        for i in range(3):
            adapter.emit(make_record(msg=f"m{i}"))
        self.assertEqual(len(sink.records), 3)
        self.assertEqual(adapter.emitted_count, 3)
        self.assertEqual(adapter.lost_count, 0)

    def test_failures_increment_lost_count_and_are_swallowed(self):
        sink = AlwaysFailingHandler()
        adapter = CountingHandlerAdapter(sink, flush_every=0)
        adapter.emit(make_record())
        adapter.emit(make_record())
        self.assertEqual(adapter.lost_count, 2)
        self.assertEqual(adapter.emitted_count, 0)
        self.assertEqual(sink.calls, 2)

    def test_flush_every_emits_summary_with_count(self):
        sink = RecordingHandler(fail_predicate=lambda r: r.name != "log_record_loss_counter")
        adapter = CountingHandlerAdapter(sink, flush_every=2)
        adapter.emit(make_record())
        self.assertEqual(len(sink.records), 0)
        adapter.emit(make_record())
        self.assertEqual(len(sink.records), 1)
        summary = sink.records[0]
        self.assertEqual(summary.name, "log_record_loss_counter")
        self.assertEqual(summary.lost_count, 2)
        self.assertEqual(summary.getMessage(), "2 log records lost")

    def test_flush_every_zero_disables_summary(self):
        sink = RecordingHandler(fail_predicate=lambda r: True)
        adapter = CountingHandlerAdapter(sink, flush_every=0)
        for _ in range(5):
            adapter.emit(make_record())
        self.assertEqual(adapter.lost_count, 5)
        self.assertEqual(len(sink.records), 0)

    def test_raise_on_error_propagates_after_counting(self):
        sink = AlwaysFailingHandler()
        adapter = CountingHandlerAdapter(sink, flush_every=0, raise_on_error=True)
        with self.assertRaises(ValueError):
            adapter.emit(make_record())
        self.assertEqual(adapter.lost_count, 1)

    def test_reset_zeroes_both_counters(self):
        sink = RecordingHandler(fail_predicate=lambda r: r.name != "log_record_loss_counter")
        adapter = CountingHandlerAdapter(sink, flush_every=0)
        adapter.emit(make_record())
        adapter.emit(make_record())
        adapter.reset()
        self.assertEqual(adapter.lost_count, 0)
        self.assertEqual(adapter.emitted_count, 0)

    def test_negative_flush_every_rejected(self):
        with self.assertRaises(ValueError):
            CountingHandlerAdapter(RecordingHandler(), flush_every=-1)

    def test_summary_uses_wrapped_handler_and_survives_its_failure(self):
        # The summary is emitted through the wrapped handler. If that handler
        # also fails on the summary, the adapter must not raise.
        sink = AlwaysFailingHandler()
        adapter = CountingHandlerAdapter(sink, flush_every=1)
        adapter.emit(make_record())
        self.assertEqual(adapter.lost_count, 1)
        # One call for the original record, one for the summary attempt.
        self.assertEqual(sink.calls, 2)

    def test_close_closes_wrapped_handler(self):
        class ClosingHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.closed = False

            def emit(self, record):
                pass

            def close(self):
                self.closed = True
                super().close()

        sink = ClosingHandler()
        adapter = CountingHandlerAdapter(sink)
        adapter.close()
        self.assertTrue(sink.closed)


class LossCountingHandlerTests(unittest.TestCase):
    def test_default_construction_uses_null_handler(self):
        adapter = LossCountingHandler()
        adapter.emit(make_record())
        self.assertEqual(adapter.emitted_count, 1)
        self.assertEqual(adapter.lost_count, 0)

    def test_alias_behaves_like_adapter(self):
        sink = AlwaysFailingHandler()
        adapter = LossCountingHandler(wrapped=sink, flush_every=0)
        adapter.emit(make_record())
        self.assertEqual(adapter.lost_count, 1)

    def test_wrapped_property_returns_sink(self):
        sink = RecordingHandler()
        adapter = LossCountingHandler(wrapped=sink)
        self.assertIs(adapter.wrapped, sink)


if __name__ == "__main__":
    unittest.main()
