"""Failed maintenance must finish all writers before caller cleanup."""

import threading
import time
import unittest
from unittest.mock import patch

from operations.workload import exercise, canonical_time


class WorkloadCleanupTest(unittest.TestCase):
    def test_failed_upgrade_joins_writers(self):
        class Controller:
            def __init__(self):
                self.active = 0
                self.calls = 0
                self.lock = threading.Lock()

            def evaluate(self, payload):
                with self.lock:
                    self.active += 1
                    self.calls += 1
                try:
                    time.sleep(0.002)
                    return payload
                finally:
                    with self.lock:
                        self.active -= 1

            def upgrade(self, candidate):
                raise RuntimeError("injected upgrade failure")

        controller = Controller()
        with patch("operations.workload.check_response"):
            with self.assertRaisesRegex(RuntimeError, "injected upgrade failure"):
                exercise(controller, "candidate", total=100)
        self.assertEqual(controller.active, 0)
        calls = controller.calls
        time.sleep(0.01)
        self.assertEqual(controller.calls, calls)
        self.assertLess(calls, 100)

    def test_input_failure_cancels_remaining_work(self):
        class Controller:
            calls = 0

            def evaluate(self, payload):
                self.calls += 1
                raise RuntimeError("input failure")

            def upgrade(self, candidate):
                raise AssertionError("must not upgrade after failed warmup")

        controller = Controller()
        with self.assertRaisesRegex(RuntimeError, "input failure"):
            exercise(controller, "candidate", total=100)
        self.assertLess(controller.calls, 100)


class TimestampNormalization(unittest.TestCase):
    def test_postgres_trimmed_fractional_seconds(self):
        for fraction in ["6", "67", "675", "6751", "67512", "675123"]:
            self.assertEqual(
                canonical_time("2026-09-30T23:45:48." + fraction + "+00:00"),
                canonical_time("2026-09-30T23:45:48." + fraction.ljust(6, "0") + "Z"),
            )

    def test_fraction_normalization_preserves_distinct_instants(self):
        self.assertNotEqual(
            canonical_time("2026-09-30T23:45:48.6751Z"),
            canonical_time("2026-09-30T23:45:48.6752Z"),
        )
