"""Run a disposable real-stack acceptance case. Requires scoped Mongo environment.

This runner never uses the installation name in the supplied template; it creates
its own unique stack. All outcomes, including failures, remain in MongoDB.
"""

import argparse
import hashlib
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from .control.controller import Controller
from .control.manifest import Manifest
from .control.storage import Storage
from .cleanup_signals import defer_interrupts


def run(
    template,
    case,
    candidate=None,
    events=20,
    crash_stage="backup",
    seed=1,
    expected_outcome="upgraded",
):
    if not 1 <= events <= 100000:
        raise ValueError("event count out of bounds")
    if (
        case
        not in [
            "install-backup",
            "install-resume",
            "diagnostics",
            "backup-integrity",
            "app-regression",
            "queue-recovery",
        ]
        and not candidate
    ):
        raise ValueError("failing candidate image required")
    config = {**asdict(template), "installation": "accept-" + uuid.uuid4().hex[:12]}
    manifest = Manifest.parse(config)
    storage = Storage.environment()
    run_id = uuid.uuid4().hex
    started = time.monotonic()
    runs = storage.db.mesops_verifications
    runs.insert_one(
        {
            "_id": run_id,
            "case": case,
            "state": "running",
            "installation": manifest.installation,
            "manifest": config,
            "candidate": candidate,
            "events_requested": events,
            "expected_outcome": expected_outcome if case == "continuous" else None,
            "crash_stage": crash_stage if case == "crash-recovery" else None,
            "source_sha256": {
                str(path.relative_to(Path(__file__).parent)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(Path(__file__).parent.rglob("*.py"))
            },
            "started_at": datetime.now(timezone.utc),
        }
    )
    password = secrets.token_hex(24)
    controller = Controller(manifest, password, storage)
    completed = False
    try:
        if case == "install-resume":
            child = subprocess.run(
                [sys.executable, "-m", "operations.crash_worker"],
                input=json.dumps(
                    {
                        "manifest": config,
                        "password": password,
                        "candidate": None,
                        "stage": "install-database",
                    }
                ).encode(),
                capture_output=True,
                timeout=120,
            )
            if child.returncode != -9:
                raise RuntimeError("installation interruption not observed")
            operation_id = controller.status()["operation_id"]
            original_database = controller.stack.require_owned("database")["Id"]
            resumed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "operations.control",
                    "resume-install",
                    "--manifest",
                    "/dev/stdin",
                    "--operation-id",
                    operation_id,
                ],
                input=json.dumps(config),
                text=True,
                capture_output=True,
                env={**os.environ, "MESOPS_DATABASE_PASSWORD": password},
                timeout=240,
            )
            if resumed.returncode or json.loads(resumed.stdout).get("state") != "ready":
                raise RuntimeError("public resume-install CLI failed")
            if controller.stack.require_owned("database")["Id"] != original_database:
                raise RuntimeError("resume replaced existing database")
            runs.update_one(
                {"_id": run_id},
                {"$set": {"worker_returncode": -9, "resume_cli_verified": True}},
            )
        else:
            controller.install()
        if case == "queue-recovery":
            from .queue_check import exercise

            result = exercise(controller)
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
            )
            completed = True
            return {"run_id": run_id, "case": case, "evidence_ref": evidence}
        if case == "app-regression":
            from .app_regression import exercise

            result = exercise(controller)
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
            )
            completed = True
            return {"run_id": run_id, "case": case, "evidence_ref": evidence}
        if case in ["backup-corrupt", "restore-failure"]:
            from .upgrade_guard_check import exercise

            result = exercise(
                controller, candidate, invalid_archive=case == "restore-failure"
            )
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
            )
            completed = True
            return {"run_id": run_id, "case": case, "evidence_ref": evidence}
        if case == "guards":
            from .guard_check import exercise

            result = exercise(controller, candidate)
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
            )
            completed = True
            return {"run_id": run_id, "case": case, "evidence_ref": evidence}
        if case in ["diagnostics", "backup-integrity"]:
            if case == "diagnostics":
                from .support_check import exercise
            else:
                from .backup_check import exercise

            result = exercise(controller)
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
            )
            completed = True
            return {"run_id": run_id, "case": case, "evidence_ref": evidence}
        if case == "continuous":
            from .workload import exercise

            result = exercise(controller, candidate, total=events, seed=seed)
            if result["upgrade_outcome"] != expected_outcome:
                raise RuntimeError("continuous workload upgrade outcome mismatch")
            evidence = storage.evidence(result)
            runs.update_one(
                {"_id": run_id},
                {"$set": {"state": "passed", "evidence_ref": evidence, "seed": seed}},
            )
            completed = True
            return {"run_id": run_id, "case": case, **result, "evidence_ref": evidence}
        timestamp = datetime.now(timezone.utc).isoformat()
        for i in range(events):
            payload = {
                "eventId": f"accept-{i}",
                "lineId": "acceptance",
                "equipmentId": f"equipment-{i % 8}",
                "limits": {"temperature": {"low": 10.0, "high": 80.0}},
                "samples": [
                    {"timestamp": timestamp, "values": {"temperature": 45.0 + i % 50}}
                ],
            }
            response = controller.evaluate(payload)
            if response.get("eventId") != payload["eventId"] or response.get("queued"):
                raise RuntimeError("workload not acknowledged")
        before = controller.stack.sql(
            "SELECT row_to_json(t)::text FROM evaluation_event t WHERE line_id='acceptance' AND event_id<>'maintenance-queued' ORDER BY event_id;"
        )
        if case in ["install-backup", "install-resume"]:
            result = controller.backup()
        elif case == "crash-recovery":
            child = subprocess.run(
                [sys.executable, "-m", "operations.crash_worker"],
                input=json.dumps(
                    {
                        "manifest": config,
                        "password": password,
                        "candidate": candidate,
                        "stage": crash_stage,
                    }
                ).encode(),
                capture_output=True,
                timeout=300,
            )
            if child.returncode != -9:
                raise RuntimeError("expected worker SIGKILL was not observed")
            operation_id = controller.status()["operation_id"]
            runs.update_one(
                {"_id": run_id},
                {
                    "$set": {
                        "worker_returncode": child.returncode,
                        "interrupted_operation": operation_id,
                    }
                },
            )
            queued_payload = {**payload, "eventId": "maintenance-queued"}
            if not controller.evaluate(queued_payload).get("queued"):
                raise RuntimeError("unfinished operation admitted input")
            result = controller.recover(operation_id)
            if result["outcome"] != "rolled_back":
                raise RuntimeError("recovery outcome mismatch")
            if int(
                controller.stack.sql(
                    "SELECT count(*) FROM pg_database WHERE datname LIKE 'mes_restore_%';"
                )
            ):
                raise RuntimeError("recovery left scratch databases")
            if storage.db.mesops_restore_resources.count_documents(
                {"installation": manifest.installation, "state": "reserved"}
            ):
                raise RuntimeError("recovery left unresolved restore reservations")
            replay = controller.replay()
            if replay["acknowledged"] != 1 or replay["pending"] != 0:
                raise RuntimeError("queued input not recovered")
        else:
            if case == "lock-timeout":
                from .lock_fault import candidate_lock

                with candidate_lock(controller, candidate) as fault:
                    result = controller.upgrade(candidate)
                if not fault["lock_confirmed"]:
                    raise RuntimeError("lock injection not verified")
            else:
                result = controller.upgrade(candidate)
            expected = "upgraded" if case == "schema-upgrade" else "rolled_back"
            if result["outcome"] != expected:
                raise RuntimeError("unexpected upgrade outcome")
            if case in ["invalid-sql", "lock-timeout", "semantic-failure"]:
                operation = controller.journal.read(controller.name)["operation"]
                step = next(x for x in operation["steps"] if x["name"] == "candidate")
                candidate_evidence = json.loads(storage.read(step["evidence_ref"]))
                codes = (
                    candidate_evidence.get("diagnostics", {})
                    .get("components", {})
                    .get("app", {})
                    .get("log_codes", [])
                )
                if case == "semantic-failure":
                    if (
                        candidate_evidence.get("diagnostics", {}).get("readiness")
                        != "UP"
                        or candidate_evidence["passed"]
                    ):
                        raise RuntimeError(
                            "healthy transport semantic failure not evidenced"
                        )
                else:
                    required_code = (
                        "database_lock_timeout"
                        if case == "lock-timeout"
                        else "migration_failed"
                    )
                    if required_code not in codes:
                        raise RuntimeError(
                            "expected migration failure not evidenced before rollback"
                        )
            if case == "schema-upgrade":
                if (
                    controller.stack.sql("SELECT version FROM mesops_release;")
                    .decode()
                    .strip()
                    != "3"
                ):
                    raise RuntimeError("release migration missing")
                if (
                    controller.stack.sql(
                        "SELECT count(*) FROM flyway_schema_history WHERE version='3' AND success;"
                    )
                    .decode()
                    .strip()
                    != "1"
                ):
                    raise RuntimeError("migration not committed")
        after = controller.stack.sql(
            "SELECT row_to_json(t)::text FROM evaluation_event t WHERE line_id='acceptance' AND event_id<>'maintenance-queued' ORDER BY event_id;"
        )
        if before != after:
            raise RuntimeError("acknowledged event records changed")
        ack = storage.db.mesops_input_queue.count_documents(
            {"installation": manifest.installation, "state": "acknowledged"}
        )
        count = int(
            controller.stack.sql(
                "SELECT count(*) FROM evaluation_event WHERE line_id='acceptance';"
            ).decode()
        )
        expected_events = events + (1 if case == "crash-recovery" else 0)
        if ack != expected_events or count != expected_events:
            raise RuntimeError("acknowledgement accounting mismatch")
        evidence = storage.evidence(
            {
                "result": result,
                "events_acknowledged": ack,
                "events_verified": count,
                "records_identical": True,
            }
        )
        runs.update_one(
            {"_id": run_id}, {"$set": {"state": "passed", "evidence_ref": evidence}}
        )
        completed = True
        return {
            "run_id": run_id,
            "case": case,
            "events": events,
            "evidence_ref": evidence,
        }
    except BaseException as exc:
        runs.update_one(
            {"_id": run_id},
            {"$set": {"state": "failed", "error_type": type(exc).__name__}},
        )
        raise
    finally:
        with defer_interrupts():
            try:
                controller.stack.destroy()
                storage.db.mesops_installations.update_one(
                    {"_id": manifest.installation}, {"$set": {"state": "removed"}}
                )
                runs.update_one(
                    {"_id": run_id},
                    {
                        "$set": {
                            "cleanup": "verified",
                            "seconds": round(time.monotonic() - started, 3),
                        }
                    },
                )
            except Exception:
                runs.update_one(
                    {"_id": run_id}, {"$set": {"cleanup": "failed", "state": "failed"}}
                )
                if completed:
                    raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--case",
        choices=[
            "install-backup",
            "install-resume",
            "startup-rollback",
            "invalid-sql",
            "semantic-failure",
            "lock-timeout",
            "schema-upgrade",
            "continuous",
            "diagnostics",
            "backup-integrity",
            "guards",
            "app-regression",
            "queue-recovery",
            "backup-corrupt",
            "restore-failure",
            "crash-recovery",
        ],
        required=True,
    )
    parser.add_argument("--candidate-image")
    parser.add_argument("--events", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--expected-outcome", choices=["upgraded", "rolled_back"], default="upgraded"
    )
    parser.add_argument(
        "--crash-stage",
        choices=[
            "backup",
            "restore-created",
            "candidate-start",
            "candidate",
            "decision",
            "service",
        ],
        default="backup",
    )
    args = parser.parse_args()
    with open(args.manifest) as f:
        manifest = Manifest.parse(json.load(f))
    print(
        json.dumps(
            run(
                manifest,
                args.case,
                args.candidate_image,
                args.events,
                args.crash_stage,
                args.seed,
                args.expected_outcome,
            ),
            indent=2,
        )
    )
