"""Full upgrade path must remain closed before an unverified backup is used."""

from datetime import datetime, timezone
import hashlib
from .control.backup import fingerprint


def exercise(controller, candidate, invalid_archive=False):
    stack = controller.stack
    before = fingerprint(stack)
    identity = stack.require_owned("app")["Id"]
    original_dump = stack.dump

    def damaged_dump():
        data, checksum = original_dump()
        if invalid_archive:
            data = b"PGDMPbroken"
            return data, hashlib.sha256(data).hexdigest()
        return data + b"changed", checksum

    stack.dump = damaged_dump
    try:
        try:
            controller.upgrade(candidate)
        except (RuntimeError, ValueError):
            pass
        else:
            raise AssertionError("unverified backup permitted upgrade")
    finally:
        stack.dump = original_dump
    status = controller.status()
    steps = {step["name"]: step["status"] for step in status["steps"]}
    if status["status"] == "completed" or steps["candidate"] != "pending":
        raise AssertionError("failed restore advanced the candidate")
    app = stack.require_owned("app")
    if app["Id"] != identity or app["State"]["Running"]:
        raise AssertionError("candidate started or ingress service remained open")
    if fingerprint(stack) != before:
        raise AssertionError("backup refusal changed authoritative records")
    payload = {
        "eventId": "blocked-maintenance-input",
        "lineId": "guard",
        "equipmentId": "synthetic",
        "limits": {"temperature": {"low": 10, "high": 80}},
        "samples": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "values": {"temperature": 45},
            }
        ],
    }
    if not controller.evaluate(payload).get("queued"):
        raise AssertionError("failed restoration admitted input")
    if int(
        stack.sql(
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'mes_restore_%';"
        )
    ):
        raise AssertionError("failed restore leaked scratch database")
    return {
        "fault": "invalid_archive" if invalid_archive else "checksum_corruption",
        "candidate_not_started": True,
        "records_preserved": True,
        "input_queued": True,
        "operation_remains_unfinished": True,
        "scope": "safe refusal, not successful recovery from a corrupt backup",
    }
