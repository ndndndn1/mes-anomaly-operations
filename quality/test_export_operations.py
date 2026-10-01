import copy
import json
import unittest
from quality.export_operations import CASES, STAGES, METRICS, build_report


def fixture():
    images = {
        key: "sha256:" + "a" * 64
        for key in ["application_image", "database_image", "cache_image"]
    }
    rows = [{"case": name, "arguments": {}} for name in CASES]
    rows += [
        {"case": "crash-recovery", "arguments": {"crash_stage": x}} for x in STAGES
    ]
    rows += [
        {"case": "continuous", "arguments": {"seed": seed, "expected_outcome": outcome}}
        for seed, outcome in [(1, "upgraded"), (2, "rolled_back")]
    ]
    children, evidence = {}, {}
    for index, row in enumerate(rows):
        row.update(run_id=str(index), state="passed")
        children[str(index)] = {
            "case": row["case"],
            "state": "passed",
            "cleanup": "verified",
            "manifest": images.copy(),
            "private_payload": "DO_NOT_EXPORT",
        }
        if row["case"] == "continuous":
            data = dict.fromkeys(METRICS, 0)
            data.update(
                events=10000,
                acknowledged=10000,
                measurements=240000,
                seed=row["arguments"]["seed"],
                upgrade_outcome=row["arguments"]["expected_outcome"],
                private_payload="DO_NOT_EXPORT",
            )
            evidence[str(index)] = data
    sources = {"operations/control/controller.py": "b" * 64}
    suite = {
        "state": "passed",
        "cases": rows,
        "source_sha256": sources,
        "manifest": images,
        "fixtures": {
            name: "sha256:" + "c" * 64
            for name in [
                "schema-upgrade",
                "invalid-sql",
                "startup-failure",
                "semantic-failure",
            ]
        },
        "private_payload": "DO_NOT_EXPORT",
    }
    return suite, children, evidence, sources


class ExportContract(unittest.TestCase):
    def test_only_public_allowlist_is_exported(self):
        report = build_report(*fixture())
        encoded = json.dumps(report)
        self.assertEqual(report["passed"], 22)
        self.assertNotIn("DO_NOT_EXPORT", encoded)
        self.assertNotIn("run_id", encoded)
        self.assertNotIn("private_payload", encoded)

    def test_incomplete_denominator_cannot_be_exported_as_success(self):
        args = fixture()
        args[0]["cases"].pop()
        with self.assertRaises(ValueError):
            build_report(*args)

    def test_duplicate_case_cannot_replace_missing_case(self):
        args = fixture()
        args[0]["cases"][0] = copy.deepcopy(args[0]["cases"][1])
        with self.assertRaises(ValueError):
            build_report(*args)

    def test_failed_cleanup_blocks_export(self):
        args = fixture()
        args[1]["0"]["cleanup"] = "failed"
        with self.assertRaises(ValueError):
            build_report(*args)

    def test_changed_source_blocks_export(self):
        suite, children, evidence, sources = fixture()
        with self.assertRaises(ValueError):
            build_report(suite, children, evidence, {**sources, "changed.py": "c" * 64})

    def test_metric_failure_or_nonfinite_cannot_pass(self):
        for key, value in [("pending", 1), ("events", 9999), ("seconds", float("nan"))]:
            args = fixture()
            next(iter(args[2].values()))[key] = value
            with self.assertRaises(ValueError):
                build_report(*args)

    def test_child_image_mismatch_blocks_export(self):
        args = fixture()
        args[1]["0"]["manifest"]["database_image"] = "sha256:" + "f" * 64
        with self.assertRaises(ValueError):
            build_report(*args)


if __name__ == "__main__":
    unittest.main()
