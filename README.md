# log-record-loss-counter-py

Wrap a logging handler and count the records it drops because of errors,
emitting a periodic summary record through the same handler.

```python
import logging
from log_record_loss_counter_py import LossCountingHandler

sink = logging.StreamHandler()
sink.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

counter = LossCountingHandler(wrapped=sink, flush_every=50)
logger = logging.getLogger("app")
logger.addHandler(counter)
logger.setLevel(logging.INFO)

logger.info("this goes to the sink")
# If the sink raises on a record, the record is counted as lost and
# swallowed. Every 50 losses a summary is written through the sink:
#   WARNING 50 log records lost

print(counter.lost_count, counter.emitted_count)
```

## Why this exists

A logging handler that raises is a nasty failure mode: the exception bubbles
out of `Logger.info` and into whatever application code happened to log. The
usual fix is to wrap the sink in a try/except, but then the fact that records
are silently disappearing is invisible. This library keeps the swallow
decision, and adds visibility: a running count plus a periodic summary that
travels through the same sink the caller already configured.

The trade-off is that the summary itself is best-effort. If the wrapped
handler is broken enough to fail on the summary record too, the summary is
dropped and only the in-process `lost_count` remains. That is deliberate: a
counting wrapper that raises on its own summary would be worse than the
problem it solves.

The summary record is a `logging.LogRecord` with `name="log_record_loss_counter"`,
`level=logging.WARNING`, `msg="%d log records lost"`, and an extra attribute
`lost_count` holding the integer. Formatters can read `record.lost_count`
directly instead of parsing the message.

## API

- `CountingHandlerAdapter(wrapped, flush_every=100, raise_on_error=False)`
- `LossCountingHandler(wrapped=None, flush_every=100, raise_on_error=False)` —
  same behaviour; `wrapped=None` means a `logging.NullHandler`.

Both expose:

- `emit(record)` — forwards to `wrapped.emit`, counts losses.
- `lost_count` — records dropped so far.
- `emitted_count` — records successfully forwarded.
- `reset()` — zeroes both counters.
- `wrapped` — the underlying handler.
- `close()` — closes the wrapped handler then this adapter.

`flush_every` must be `>= 0`; `0` disables the summary. `raise_on_error=True`
re-raises the sink exception after counting it, for callers who want the
original behaviour plus the count.

## The awkward edge

The flush is triggered on the *n*-th loss where `n` is a multiple of
`flush_every`, and the summary is emitted through the wrapped handler. If the
wrapped handler fails on the summary as well, that failure is swallowed and
the summary is simply lost — the count is still correct and will trigger
again on the next multiple. Threads sharing one adapter are safe: the
counters are guarded by an internal lock, and the summary is emitted after
releasing it so a wrapped handler that logs during its own emit cannot
deadlock the adapter.
