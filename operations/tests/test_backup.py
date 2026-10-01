import hashlib
import unittest
from operations.control.backup import verify_restore, identifier, sequence_fingerprint


class UnreachableStack:
    def require_owned(self, role):
        raise AssertionError(
            "invalid backup must be rejected before database operation"
        )


class BackupGuards(unittest.TestCase):
    def test_checksum_mismatch_never_touches_database(self):
        with self.assertRaises(ValueError):
            verify_restore(UnreachableStack(), b"PGDMPcorrupt", "wrong", {})

    def test_invalid_format_with_valid_hash_never_touches_database(self):
        data = b"not a postgres dump"
        with self.assertRaises(ValueError):
            verify_restore(
                UnreachableStack(), data, hashlib.sha256(data).hexdigest(), {}
            )

    def test_database_identifier_quotes_are_escaped(self):
        self.assertEqual(identifier('quoted"table'), '"quoted""table"')


class SequenceState(unittest.TestCase):
    def test_same_last_value_different_next_id_is_not_equal(self):
        class Stack:
            def __init__(self, called):
                self.called = called

            def sql(self, query, database):
                if "json_agg" in query:
                    return b'["sample_id_seq"]'
                if "is_called" in query:
                    return b"7|t" if self.called else b"7|f"
                return b"sample_id_seq|bigint|1|1|999|1|f|1"

        self.assertNotEqual(
            sequence_fingerprint(Stack(True)), sequence_fingerprint(Stack(False))
        )


if __name__ == "__main__":
    unittest.main()
