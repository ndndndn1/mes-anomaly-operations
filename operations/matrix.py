"""Execute the complete acceptance matrix sequentially on one immutable release.

All cases remain in the denominator. Failure stops the suite with the remaining
cases unexecuted. Each attempt and cleanup outcome is preserved in MongoDB.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from .acceptance import run
from .fixtures import build
from .control.manifest import Manifest
from .control.storage import Storage


def source_snapshot(root):
    files = [
        path
        for folder in ["operations", "src", "test"]
        for path in sorted((root / folder).rglob("*"))
        if path.is_file()
        and path.suffix
        in [".py", ".java", ".sql", ".lean", ".yml", ".properties", ".Dockerfile"]
    ]
    files += [
        root / name
        for name in [
            "Dockerfile",
            "pom.xml",
            "compose.yaml",
            "operations/requirements.txt",
            "web/package-lock.json",
        ]
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def execute(manifest):
    storage = Storage.environment()
    identifier = uuid.uuid4().hex
    cases = [
        ("install-backup", None, {}),
        ("install-resume", None, {}),
        ("diagnostics", None, {}),
        ("backup-integrity", None, {}),
        ("guards", "schema-upgrade", {}),
        ("app-regression", None, {}),
        ("backup-corrupt", "schema-upgrade", {}),
        ("restore-failure", "schema-upgrade", {}),
        ("queue-recovery", None, {}),
        ("schema-upgrade", "schema-upgrade", {}),
        ("startup-rollback", "startup-failure", {}),
        ("invalid-sql", "invalid-sql", {}),
        ("semantic-failure", "semantic-failure", {}),
        ("lock-timeout", "schema-upgrade", {}),
    ]
    cases += [
        ("crash-recovery", "schema-upgrade", {"crash_stage": stage})
        for stage in [
            "backup",
            "restore-created",
            "candidate-start",
            "candidate",
            "decision",
            "service",
        ]
    ]
    cases += [
        (
            "continuous",
            "schema-upgrade",
            {"events": 10000, "seed": 1, "expected_outcome": "upgraded"},
        ),
        (
            "continuous",
            "invalid-sql",
            {"events": 10000, "seed": 2, "expected_outcome": "rolled_back"},
        ),
    ]
    root = Path(__file__).resolve().parents[1]
    sources = source_snapshot(root)
    rows = [
        {"case": case, "fixture": fixture, "arguments": args, "state": "unexecuted"}
        for case, fixture, args in cases
    ]
    collection = storage.db.mesops_suites
    collection.insert_one(
        {
            "_id": identifier,
            "state": "running",
            "manifest": asdict(manifest),
            "source_sha256": sources,
            "cases": rows,
            "started_at": datetime.now(timezone.utc),
        }
    )
    print(json.dumps({"suite": identifier, "total": len(cases)}), flush=True)
    try:
        fixtures = {
            kind: build(manifest.application_image, kind)["image"]
            for kind in [
                "schema-upgrade",
                "invalid-sql",
                "startup-failure",
                "semantic-failure",
            ]
        }
        collection.update_one({"_id": identifier}, {"$set": {"fixtures": fixtures}})
        for index, (case, fixture, args) in enumerate(cases):
            rows[index]["state"] = "running"
            collection.update_one({"_id": identifier}, {"$set": {"cases": rows}})
            result = run(manifest, case, candidate=fixtures.get(fixture), **args)
            rows[index].update(state="passed", run_id=result["run_id"])
            collection.update_one({"_id": identifier}, {"$set": {"cases": rows}})
            print(
                json.dumps(
                    {
                        "suite": identifier,
                        "case": index + 1,
                        "total": len(cases),
                        "name": case,
                        "arguments": args,
                        "state": "passed",
                    }
                ),
                flush=True,
            )
        if source_snapshot(root) != sources:
            raise RuntimeError("acceptance sources changed during execution")
        collection.update_one(
            {"_id": identifier},
            {"$set": {"state": "passed", "completed_at": datetime.now(timezone.utc)}},
        )
    except BaseException as exc:
        for row in rows:
            if row["state"] == "running":
                row.update(state="failed", error_type=type(exc).__name__)
        collection.update_one(
            {"_id": identifier},
            {
                "$set": {
                    "state": "failed",
                    "cases": rows,
                    "error_type": type(exc).__name__,
                }
            },
        )
        raise
    return identifier


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    with open(args.manifest) as source:
        manifest = Manifest.parse(json.load(source))
    execute(manifest)
