import unittest
from operations.control.stack import Stack, InputRejected


class HTTPOutcomes(unittest.TestCase):
    def stack(self, response):
        from operations.control.manifest import Manifest

        digest = "sha256:" + "a" * 64
        stack = Stack(Manifest("http-test", digest, digest, digest), "test-only")
        stack.require_owned = lambda role: None
        stack.command = lambda *args, **kwargs: response
        return stack

    def test_known_invalid_input_is_definitive_rejection(self):
        with self.assertRaises(InputRejected) as context:
            self.stack(b'{"detail":"invalid"}\n422').api("/api/v1/evaluations", {})
        self.assertEqual(context.exception.status, 422)

    def test_rate_limit_and_server_error_remain_retryable(self):
        for status in [429, 500, 503, 401]:
            with self.assertRaises(RuntimeError) as context:
                self.stack(b"{}\n" + str(status).encode()).api(
                    "/api/v1/evaluations", {}
                )
            self.assertNotIsInstance(context.exception, InputRejected)

    def test_body_newlines_do_not_confuse_status_parser(self):
        self.assertEqual(
            self.stack(b'{\n"status":"UP"\n}\n200').api("/actuator/health"),
            {"status": "UP"},
        )
