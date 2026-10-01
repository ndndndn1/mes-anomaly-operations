"""Defer operator interruption until bounded disposable-resource cleanup finishes."""

from contextlib import contextmanager
import signal


@contextmanager
def defer_interrupts():
    pending = []
    previous = {}

    def remember(signum, frame):
        pending.append(signum)

    try:
        for signum in [signal.SIGINT, signal.SIGTERM]:
            previous[signum] = signal.signal(signum, remember)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if pending:
            if signal.SIGINT in pending:
                raise KeyboardInterrupt
            raise SystemExit(128 + pending[0])
