import signal
import unittest
from operations.cleanup_signals import defer_interrupts


class CleanupSignals(unittest.TestCase):
    def test_interrupt_is_delivered_after_cleanup_body(self):
        previous = signal.getsignal(signal.SIGINT)
        finished = []
        with self.assertRaises(KeyboardInterrupt):
            with defer_interrupts():
                signal.raise_signal(signal.SIGINT)
                finished.append(True)
        self.assertEqual(finished, [True])
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)
