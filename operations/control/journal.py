"""Durable intents in MongoDB. A lost response requires reconciliation, not retry.

One document per installation makes transitions atomic without multi-document
transactions. Callers must also hold HostLock for the entire local Docker action.
An unfinished operation is never stolen merely because its owner stopped.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
import uuid


class Conflict(RuntimeError):
    pass


class ReconciliationRequired(RuntimeError):
    pass


@contextmanager
def host_lock(installation, shared=False):
    name = hashlib.sha256(installation.encode()).hexdigest()
    fd = os.open(
        "/tmp/mesops-" + name + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class Journal:
    def __init__(self, collection):
        self.collection = collection

    def read(self, installation):
        return self.collection.find_one({"_id": installation})

    def begin(self, installation, kind, manifest, steps):
        if not steps or len(set(steps)) != len(steps):
            raise ValueError("unique ordered steps required")
        # setOnInsert keeps an existing operation intact. MongoDB _id is unique.
        try:
            self.collection.update_one(
                {"_id": installation},
                {"$setOnInsert": {"revision": 0, "operation": None}},
                upsert=True,
            )
        except Exception:
            # Includes unknown write outcomes. Caller must reread, not assume failure.
            raise ReconciliationRequired(
                "journal initialization outcome unknown"
            ) from None
        old = self.read(installation)
        if old["operation"] and old["operation"]["status"] != "completed":
            raise Conflict("unfinished operation: resume exact operation ID")
        operation = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "manifest": manifest,
            "status": "active",
            "started_at": datetime.now(timezone.utc),
            "steps": [{"name": x, "status": "pending"} for x in steps],
        }
        self._write(old, operation, archive=True)
        return operation["id"]

    def _write(self, old, operation, archive=False):
        update = {"$set": {"operation": operation}, "$inc": {"revision": 1}}
        if archive and old.get("operation"):
            if len(old.get("history", [])) >= 100:
                raise Conflict(
                    "journal history requires verified archival before new operation"
                )
            update["$push"] = {"history": old["operation"]}
        try:
            result = self.collection.update_one(
                {"_id": old["_id"], "revision": old["revision"]},
                update,
            )
        except Exception:
            raise ReconciliationRequired(
                "journal write outcome unknown; inspect persisted revision"
            ) from None
        if result.modified_count != 1:
            raise Conflict("concurrent journal revision")

    def _load(self, installation, operation_id):
        old = self.read(installation)
        if (
            not old
            or not old.get("operation")
            or old["operation"]["id"] != operation_id
        ):
            raise Conflict("operation identity mismatch")
        if old["operation"]["status"] != "active":
            raise Conflict("operation is terminal")
        return old

    def intent(self, installation, operation_id, step):
        old = self._load(installation, operation_id)
        operation = old["operation"]
        target = next((x for x in operation["steps"] if x["name"] == step), None)
        if target is None:
            raise ValueError("unknown step")
        if target["status"] in ("running", "uncertain"):
            raise ReconciliationRequired("inspect external outcome before retry")
        if target["status"] == "verified":
            return False
        if target["status"] != "pending":
            raise Conflict("step cannot run")
        index = operation["steps"].index(target)
        if any(x["status"] != "verified" for x in operation["steps"][:index]):
            raise Conflict("previous step not verified")
        target.update(status="running", intent_at=datetime.now(timezone.utc))
        self._write(old, operation)
        return True

    def verified(self, installation, operation_id, step, evidence_ref):
        if not isinstance(evidence_ref, str) or not evidence_ref:
            raise ValueError("persisted evidence reference required")
        old = self._load(installation, operation_id)
        target = next((x for x in old["operation"]["steps"] if x["name"] == step), None)
        if target is None or target["status"] not in ("running", "uncertain"):
            raise Conflict("no intent to reconcile")
        target.update(
            status="verified",
            evidence_ref=evidence_ref,
            verified_at=datetime.now(timezone.utc),
        )
        self._write(old, old["operation"])

    def uncertain(self, installation, operation_id, step):
        old = self._load(installation, operation_id)
        target = next((x for x in old["operation"]["steps"] if x["name"] == step), None)
        if target is None or target["status"] != "running":
            raise Conflict("no running step")
        target["status"] = "uncertain"
        self._write(old, old["operation"])

    def complete(self, installation, operation_id, outcome="completed"):
        if outcome not in {
            "completed",
            "installed",
            "backup_verified",
            "upgraded",
            "rolled_back",
        }:
            raise ValueError("unknown completion outcome")
        old = self._load(installation, operation_id)
        if any(x["status"] != "verified" for x in old["operation"]["steps"]):
            raise Conflict("unverified steps remain")
        old["operation"].update(
            status="completed", outcome=outcome, completed_at=datetime.now(timezone.utc)
        )
        self._write(old, old["operation"])

    def recovery_intent(self, installation, operation_id):
        old = self._load(installation, operation_id)
        if not old["operation"].get("recovery"):
            old["operation"]["recovery"] = {
                "direction": "rollback",
                "status": "running",
                "started_at": datetime.now(timezone.utc),
            }
            self._write(old, old["operation"])

    def recovered(self, installation, operation_id, evidence_ref):
        if not evidence_ref:
            raise ValueError("recovery evidence required")
        old = self._load(installation, operation_id)
        if old["operation"].get("recovery", {}).get("direction") != "rollback":
            raise Conflict("missing recovery intent")
        for step in old["operation"]["steps"]:
            if step["status"] == "pending":
                step.update(status="skipped", reason="aborted before execution")
            elif step["status"] in ("running", "uncertain"):
                step.update(
                    status="reconciled",
                    reason="interrupted operation recovered to original release",
                )
        old["operation"].update(
            status="completed",
            outcome="rolled_back",
            completed_at=datetime.now(timezone.utc),
        )
        old["operation"]["recovery"].update(
            status="verified", evidence_ref=evidence_ref
        )
        self._write(old, old["operation"])
