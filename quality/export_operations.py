"""Export only verified synthetic acceptance fields; never export private DB rows."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    "install-backup",
    "install-resume",
    "diagnostics",
    "backup-integrity",
    "guards",
    "app-regression",
    "backup-corrupt",
    "restore-failure",
    "queue-recovery",
    "schema-upgrade",
    "startup-rollback",
    "invalid-sql",
    "semantic-failure",
    "lock-timeout",
]
STAGES = [
    "backup",
    "restore-created",
    "candidate-start",
    "candidate",
    "decision",
    "service",
]
METRICS = [
    "events",
    "measurements",
    "acknowledged",
    "duplicate_events",
    "lost_acknowledged_events",
    "pending",
    "seconds",
    "seed",
    "workers",
    "acknowledgement_p95_seconds",
    "effective_events_per_second",
    "input_attempt_p95_seconds",
    "maintenance_and_producer_seconds",
    "queued_during_maintenance",
    "write_gate_closed_seconds",
]


def identity(row):
    args = row["arguments"]
    return (row["case"], args.get("crash_stage"), args.get("seed"))


def build_report(suite, children, evidence, current_sources):
    expected = Counter(
        [(x, None, None) for x in CASES]
        + [("crash-recovery", x, None) for x in STAGES]
        + [("continuous", None, x) for x in [1, 2]]
    )
    if (
        suite.get("state") != "passed"
        or Counter(identity(x) for x in suite["cases"]) != expected
        or any(x["state"] != "passed" for x in suite["cases"])
    ):
        raise ValueError("complete 22-case terminal acceptance required")
    if not current_sources or suite["source_sha256"] != current_sources:
        raise ValueError("implementation no longer matches accepted source")
    images = {}
    for key in ["application_image", "database_image", "cache_image"]:
        value = suite["manifest"][key]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("resolved immutable image ID required")
        images[key] = value
    fixtures = suite.get("fixtures", {})
    required_fixtures = {
        "schema-upgrade",
        "invalid-sql",
        "startup-failure",
        "semantic-failure",
    }
    if set(fixtures) != required_fixtures or any(
        not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
        for value in fixtures.values()
    ):
        raise ValueError("complete immutable fixture image identities required")
    rows = []
    for case in suite["cases"]:
        child = children[case["run_id"]]
        if child.get("state") != "passed" or child.get("cleanup") != "verified":
            raise ValueError("child acceptance or cleanup is unverified")
        if child["case"] != case["case"]:
            raise ValueError("child case mismatch")
        if any(child["manifest"][key] != value for key, value in images.items()):
            raise ValueError("child image mismatch")
        row = {"case": case["case"], "state": "passed", "cleanup": "verified"}
        if case["arguments"].get("crash_stage"):
            row["crash_stage"] = case["arguments"]["crash_stage"]
        if case["case"] == "continuous":
            data = evidence[case["run_id"]]
            metrics = {}
            for key in METRICS:
                value = data[key]
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("invalid synthetic metric")
                metrics[key] = value
            outcome = case["arguments"]["expected_outcome"]
            if (
                outcome not in ["upgraded", "rolled_back"]
                or data["upgrade_outcome"] != outcome
                or metrics["seed"] != case["arguments"]["seed"]
                or metrics["events"] != 10000
                or metrics["acknowledged"] != 10000
                or metrics["measurements"] != 240000
                or any(
                    metrics[k] != 0
                    for k in ["lost_acknowledged_events", "duplicate_events", "pending"]
                )
            ):
                raise ValueError("large-workload acceptance mismatch")
            row.update(metrics=metrics, outcome=outcome)
        rows.append(row)
    return {
        "scope": "Synthetic MES reference stack; not KLA, Oracle or customer validation",
        "passed": len(rows),
        "total": 22,
        "failed": 0,
        "unexecuted": 0,
        "images": images,
        "fixture_images": fixtures,
        "source_sha256": current_sources,
        "cases": rows,
        "limitations": [
            "Acknowledgement latency includes operator-driven queue replay.",
            "Image vulnerability results and Lean proofs are separate gates.",
            "Earlier failed and interrupted attempts remain in private evidence.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from operations.control.storage import Storage
    from operations.matrix import source_snapshot

    storage = Storage.environment()
    suite = storage.db.mesops_suites.find_one({"_id": args.suite_id})
    if not suite:
        raise ValueError("suite not found")
    children, evidence = {}, {}
    for row in suite["cases"]:
        if not row.get("run_id"):
            raise ValueError("case has no completed run")
        child = storage.db.mesops_verifications.find_one({"_id": row["run_id"]})
        if not child:
            raise ValueError("child run not found")
        children[row["run_id"]] = child
        if row["case"] == "continuous":
            evidence[row["run_id"]] = json.loads(storage.read(child["evidence_ref"]))
    report = build_report(suite, children, evidence, source_snapshot(ROOT))
    report["exporter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # Refuse accidental overwrite. A new report is explicitly reviewed before replacement.
    with args.output.open("x") as target:
        json.dump(report, target, indent=2, sort_keys=True)
        target.write("\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"]}))


if __name__ == "__main__":
    main()
