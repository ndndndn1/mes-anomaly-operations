import unittest
from operations.control.diagnostics import classify_logs


class Diagnostics(unittest.TestCase):
    def test_sensitive_logs_only_emit_known_codes(self):
        secret = "sample-secret-password-and-customer-payload"
        result = classify_logs("FlywayMigrateException lock timeout " + secret)
        self.assertEqual(result, ["database_lock_timeout", "migration_failed"])
        self.assertNotIn(secret, str(result))

    def test_unrecognized_log_content_is_not_exported(self):
        self.assertEqual(
            classify_logs("private event identifier and arbitrary diagnostic text"), []
        )


if __name__ == "__main__":
    unittest.main()
