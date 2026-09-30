import unittest
from unittest.mock import patch
from operations.rehearse import execute, sql


class ContractTests(unittest.TestCase):
    def test_sql_stays_on_stdin_and_stops_on_error(self):
        with patch("operations.rehearse.execute") as command:
            sql("mes-rehearsal-test", "SELECT 1;")
        args, kwargs = command.call_args
        self.assertIn("ON_ERROR_STOP=1", args[0])
        self.assertNotIn("SELECT 1;", args[0])
        self.assertEqual(kwargs["data"], "SELECT 1;")

    def test_process_timeout_and_no_shell(self):
        with patch("subprocess.run") as call:
            execute(["docker", "version"])
        self.assertEqual(call.call_args.kwargs["timeout"], 40)
        self.assertNotIn("shell", call.call_args.kwargs)
