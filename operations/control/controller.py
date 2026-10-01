"""Operator workflows over a scoped Mongo journal and the managed stack."""

from dataclasses import asdict
from datetime import datetime, timezone
from .backup import fingerprint, verify_restore
from .journal import Journal, host_lock, Conflict
from .preflight import inspect, Docker
from .stack import Stack, InputRejected
from .restore_resources import RestoreResources


class Controller:
    def __init__(self, manifest, password, storage):
        self.manifest = manifest
        self.stack = Stack(manifest, password)
        self.storage = storage
        self.journal = Journal(storage.db.mesops_journals)
        self.name = manifest.installation

    def _verified(self, op, step, evidence):
        ref = self.storage.evidence(evidence)
        self.journal.verified(self.name, op, step, ref)
        return ref

    def _component(self, op, role, create, ready, image):
        doc = self.journal.read(self.name)["operation"]
        step = next(x for x in doc["steps"] if x["name"] == role)
        if step["status"] == "verified":
            data = self.stack.require_owned(role)
            if data["Image"] != Docker().image(image)["Id"]:
                raise Conflict("verified component image drift")
            ready()
            return
        if step["status"] == "pending":
            self.journal.intent(self.name, op, role)
        existing = Docker().container(self.manifest.container(role))
        if existing is None:
            create()
        else:
            data = self.stack.require_owned(role)
            if data["Image"] != Docker().image(image)["Id"]:
                raise Conflict("component image drift")
            if not data["State"]["Running"]:
                self.stack.command(["start", self.manifest.container(role)])
        ready()
        self._verified(
            op, role, {"image_id": Docker().image(image)["Id"], "ready": True}
        )

    def semantic_probe(self, op):
        started = self.journal.read(self.name)["operation"]["started_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        # Same event ID and payload on recovery: this tests the real idempotent API.
        payload = {
            "eventId": "mesops-probe-" + op,
            "lineId": "mesops-validation",
            "equipmentId": "synthetic-probe",
            "limits": {"temperature": {"low": 10.0, "high": 80.0}},
            "samples": [
                {"timestamp": started.isoformat(), "values": {"temperature": 95.0}}
            ],
        }
        result = self.stack.api("/api/v1/evaluations", payload)
        if (
            result.get("eventId") != payload["eventId"]
            or result.get("evaluated") != 1
            or not result.get("verdicts")
        ):
            raise RuntimeError("semantic readiness failed")
        verdict = result["verdicts"][0]
        if (
            verdict.get("value") != 95.0
            or verdict.get("sensor") != "temperature"
            or verdict.get("severity") != "critical"
            or verdict.get("rule") != "absolute_limit"
        ):
            raise RuntimeError("semantic verdict mismatch")
        count = int(
            self.stack.sql(
                "SELECT count(*) FROM evaluation_event WHERE event_id='"
                + payload["eventId"]
                + "' AND completed_at IS NOT NULL;"
            ).decode()
        )
        if count != 1:
            raise RuntimeError("API acknowledgement not durable")
        replay = self.stack.api("/api/v1/evaluations", payload)
        if not replay.get("replayed") or {
            k: v for k, v in replay.items() if k != "replayed"
        } != {k: v for k, v in result.items() if k != "replayed"}:
            raise RuntimeError("semantic replay mismatch")
        children = int(
            self.stack.sql(
                "SELECT count(*) FROM sensor_verdict WHERE event_id='"
                + payload["eventId"]
                + "' AND sensor='temperature' AND value=95 AND severity='critical' AND rule_name='absolute_limit';"
            )
        )
        samples = int(
            self.stack.sql(
                "SELECT count(*) FROM sensor_sample WHERE event_id='"
                + payload["eventId"]
                + "' AND sensor='temperature' AND value=95;"
            )
        )
        if children != 1 or samples != 1:
            raise RuntimeError("semantic child records mismatch")
        return {
            "event_id": payload["eventId"],
            "durable_events": count,
            "evaluated": 1,
            "replay_verified": True,
            "child_records_verified": True,
        }

    def install(self, resume=None):
        with host_lock(self.name):
            if resume:
                doc = self.journal._load(self.name, resume)["operation"]
                if doc["kind"] != "install" or doc["manifest"] != asdict(self.manifest):
                    raise Conflict("resume contract mismatch")
                op = resume
            else:
                preflight = inspect(self.manifest)
                if not preflight["ok"] or any(
                    c.get("exists") for c in preflight["checks"]
                ):
                    raise Conflict(
                        "fresh installation requires absent components and valid inventory"
                    )
                op = self.journal.begin(
                    self.name,
                    "install",
                    asdict(self.manifest),
                    ["database", "cache", "app", "semantic"],
                )
            self._component(
                op,
                "database",
                lambda: self.stack.create_database(reuse_owned_volume=bool(resume)),
                self.stack.wait_database,
                self.manifest.database_image,
            )
            self._component(
                op,
                "cache",
                self.stack.create_cache,
                lambda: self.stack.command(
                    ["exec", self.manifest.container("cache"), "redis-cli", "ping"]
                ),
                self.manifest.cache_image,
            )
            self._component(
                op,
                "app",
                self.stack.create_app,
                self.stack.wait_application,
                self.manifest.application_image,
            )
            step = self.journal.read(self.name)["operation"]["steps"][-1]
            if step["status"] == "pending":
                self.journal.intent(self.name, op, "semantic")
            if step["status"] != "verified":
                self._verified(op, "semantic", self.semantic_probe(op))
            self.storage.db.mesops_installations.update_one(
                {"_id": self.name},
                {
                    "$set": {
                        "manifest": asdict(self.manifest),
                        "state": "ready",
                        "installed_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            self.journal.complete(self.name, op, "installed")
            return {"operation_id": op, "state": "ready"}

    def backup(self):
        with host_lock(self.name):
            op = self.journal.begin(
                self.name,
                "backup",
                asdict(self.manifest),
                ["drain", "backup", "restore-check", "restart"],
            )
            self.journal.intent(self.name, op, "drain")
            self.stack.stop_app()
            self._verified(op, "drain", {"stopped": True, "other_clients": 0})
            self.journal.intent(self.name, op, "backup")
            before = fingerprint(self.stack)
            data, checksum = self.stack.dump()
            ref = self.storage.blob(data, "postgres.dump")
            self._verified(
                op,
                "backup",
                {"backup_ref": ref, "checksum": checksum, "fingerprint": before},
            )
            self.journal.intent(self.name, op, "restore-check")
            result = verify_restore(
                self.stack,
                self.storage.read(ref),
                checksum,
                before,
                RestoreResources(self.stack, self.storage, op),
            )
            self._verified(op, "restore-check", result)
            self.journal.intent(self.name, op, "restart")
            self.stack.command(["start", self.manifest.container("app")])
            self.stack.wait_application()
            if fingerprint(self.stack) != before:
                raise RuntimeError("restart changed existing records")
            self._verified(
                op, "restart", {"ready": True, "fingerprint_preserved": True}
            )
            self.journal.complete(self.name, op, "backup_verified")
            return {
                "operation_id": op,
                "backup_ref": ref,
                "verified_restore": True,
                "state": "ready",
            }

    def status(self):
        doc = self.journal.read(self.name)
        if not doc:
            return {"installation": self.name, "operation": None}
        op = doc["operation"]
        return {
            "installation": self.name,
            "revision": doc["revision"],
            "operation_id": op["id"],
            "kind": op["kind"],
            "status": op["status"],
            "outcome": op.get("outcome"),
            "steps": [{"name": s["name"], "status": s["status"]} for s in op["steps"]],
        }

    def evaluate(self, payload):
        # All supported client input goes through this shared lock; upgrades hold EX.
        # Record intent before attempting HTTP so lost responses can be replayed.
        import hashlib
        import json

        if not isinstance(payload, dict) or not isinstance(payload.get("eventId"), str):
            raise ValueError("eventId required")
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        key = hashlib.sha256(
            (self.name + "\0" + payload["eventId"]).encode()
        ).hexdigest()
        coll = self.storage.db.mesops_input_queue
        coll.update_one(
            {"_id": key},
            {
                "$setOnInsert": {
                    "installation": self.name,
                    "event_id": payload["eventId"],
                    "payload": payload,
                    "payload_hash": digest,
                    "state": "pending",
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        record = coll.find_one({"_id": key})
        if record["payload_hash"] != digest:
            raise Conflict("event ID reused with different payload")
        if record["state"] == "rejected":
            return {
                "rejected": True,
                "eventId": payload["eventId"],
                "http_status": record["http_status"],
            }
        if record["state"] == "acknowledged":
            return record["response"]
        try:
            with host_lock(self.name, shared=True):
                installation = self.storage.db.mesops_installations.find_one(
                    {"_id": self.name}
                )
                journal = self.journal.read(self.name)
                unfinished = bool(
                    journal
                    and journal.get("operation")
                    and journal["operation"]["status"] != "completed"
                )
                if not installation or installation["state"] != "ready" or unfinished:
                    return {"queued": True, "eventId": payload["eventId"]}
                try:
                    result = self.stack.api("/api/v1/evaluations", payload)
                except InputRejected as exc:
                    changed = coll.update_one(
                        {"_id": key, "payload_hash": digest, "state": "pending"},
                        {
                            "$set": {
                                "state": "rejected",
                                "http_status": exc.status,
                                "rejected_at": datetime.now(timezone.utc),
                            }
                        },
                    )
                    if not changed.matched_count:
                        saved = coll.find_one({"_id": key})
                        if saved and saved.get("state") == "acknowledged":
                            return saved["response"]
                        if not saved or saved.get("state") != "rejected":
                            raise RuntimeError("rejection persistence conflict")
                    return {
                        "rejected": True,
                        "eventId": payload["eventId"],
                        "http_status": exc.status,
                    }
                if result.get("eventId") != payload["eventId"]:
                    raise RuntimeError("unexpected response identity")
                acknowledgement = coll.update_one(
                    {"_id": key, "payload_hash": digest, "state": "pending"},
                    {
                        "$set": {
                            "state": "acknowledged",
                            "response": result,
                            "acknowledged_at": datetime.now(timezone.utc),
                        }
                    },
                )
                if not acknowledgement.matched_count:
                    saved = coll.find_one({"_id": key})
                    if (
                        not saved
                        or saved.get("state") != "acknowledged"
                        or saved.get("payload_hash") != digest
                    ):
                        raise RuntimeError("acknowledgement persistence conflict")
                return result
        except BlockingIOError:
            return {"queued": True, "eventId": payload["eventId"]}

    def replay(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("invalid bounded replay limit")
        processed = 0
        rejected = 0
        for item in (
            self.storage.db.mesops_input_queue.find(
                {"installation": self.name, "state": "pending"}
            )
            .sort("created_at", 1)
            .limit(limit)
        ):
            result = self.evaluate(item["payload"])
            if result.get("queued"):
                break
            if result.get("rejected"):
                rejected += 1
            else:
                processed += 1
        return {
            "acknowledged": processed,
            "rejected": rejected,
            "pending": self.storage.db.mesops_input_queue.count_documents(
                {"installation": self.name, "state": "pending"}
            ),
        }

    def upgrade(self, candidate_image):
        import subprocess
        from .manifest import IMAGE
        from .backup import restore_original

        if not isinstance(candidate_image, str) or not IMAGE.fullmatch(candidate_image):
            raise ValueError("immutable candidate image required")
        candidate_id = Docker().image(candidate_image)["Id"]
        with host_lock(self.name):
            installed = self.storage.db.mesops_installations.find_one(
                {"_id": self.name}
            )
            if (
                not installed
                or installed["state"] != "ready"
                or installed["manifest"] != asdict(self.manifest)
            ):
                raise Conflict(
                    "deployment manifest/state differs from current installation"
                )
            self.stack.wait_application()
            op = self.journal.begin(
                self.name,
                "upgrade",
                {**asdict(self.manifest), "candidate_image": candidate_image},
                [
                    "drain",
                    "backup",
                    "restore-check",
                    "candidate",
                    "decision",
                    "service",
                ],
            )
            self.storage.db.mesops_installations.update_one(
                {"_id": self.name}, {"$set": {"state": "maintenance"}}
            )
            self.journal.intent(self.name, op, "drain")
            self.stack.stop_app()
            self._verified(op, "drain", {"stopped": True})
            self.journal.intent(self.name, op, "backup")
            original = fingerprint(self.stack)
            backup, checksum = self.stack.dump()
            backup_ref = self.storage.blob(backup, "upgrade-backup.dump")
            self._verified(
                op,
                "backup",
                {
                    "backup_ref": backup_ref,
                    "checksum": checksum,
                    "fingerprint": original,
                },
            )
            self.journal.intent(self.name, op, "restore-check")
            self._verified(
                op,
                "restore-check",
                verify_restore(
                    self.stack,
                    self.storage.read(backup_ref),
                    checksum,
                    original,
                    RestoreResources(self.stack, self.storage, op),
                ),
            )
            self.journal.intent(self.name, op, "candidate")
            candidate_ok = False
            try:
                self.stack.require_owned("app")
                self.stack.command(["rm", self.manifest.container("app")])
                self.stack.create_app(candidate_image)
                self.stack.wait_application()
                after = fingerprint(self.stack)
                # Flyway history/schema can legitimately change; all existing business tables must retain rows.
                for table, value in original.items():
                    if (
                        isinstance(value, dict)
                        and table != "flyway_schema_history"
                        and after.get(table) != value
                    ):
                        raise RuntimeError(
                            "candidate modified existing business records"
                        )
                self.semantic_probe(op)
                candidate_ok = True
                evidence = {
                    "passed": True,
                    "image_id": candidate_id,
                    "existing_records_preserved": True,
                }
            except (RuntimeError, subprocess.TimeoutExpired):
                evidence = {
                    "passed": False,
                    "image_id": candidate_id,
                    "reason": "candidate startup or semantic/data validation failed",
                }
                # Collect before replacing the failed container; otherwise its
                # migration/configuration evidence disappears during rollback.
                from .diagnostics import diagnose

                try:
                    evidence["diagnostics"] = diagnose(self)
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    evidence["diagnostics"] = {"collection": "unavailable"}
            self._verified(op, "candidate", evidence)
            self.journal.intent(self.name, op, "decision")
            if candidate_ok:
                new_manifest = {
                    **asdict(self.manifest),
                    "application_image": candidate_image,
                }
                self._verified(
                    op, "decision", {"decision": "promote", "image_id": candidate_id}
                )
            else:
                existing = Docker().container(self.manifest.container("app"))
                if existing:
                    self.stack.require_owned("app")
                    self.stack.command(
                        [
                            "stop",
                            "--time",
                            str(self.manifest.drain_seconds),
                            self.manifest.container("app"),
                        ]
                    )
                restore_original(
                    self.stack, self.storage.read(backup_ref), checksum, original
                )
                if existing:
                    self.stack.command(["rm", self.manifest.container("app")])
                self.stack.create_app()
                self.stack.wait_application()
                if fingerprint(self.stack) != original:
                    raise RuntimeError("rollback did not preserve original data/schema")
                self.semantic_probe(op)
                new_manifest = asdict(self.manifest)
                self._verified(
                    op,
                    "decision",
                    {
                        "decision": "rollback",
                        "restored_backup": backup_ref,
                        "original_verified": True,
                    },
                )
            self.journal.intent(self.name, op, "service")
            self.stack.wait_application()
            self.storage.db.mesops_installations.update_one(
                {"_id": self.name},
                {
                    "$set": {
                        "state": "ready",
                        "manifest": new_manifest,
                        "last_upgrade_operation": op,
                    }
                },
            )
            self._verified(
                op,
                "service",
                {
                    "ready": True,
                    "outcome": "upgraded" if candidate_ok else "rolled_back",
                },
            )
            self.journal.complete(
                self.name, op, "upgraded" if candidate_ok else "rolled_back"
            )
            return {
                "operation_id": op,
                "outcome": "upgraded" if candidate_ok else "rolled_back",
                "manifest": new_manifest,
                "backup_ref": backup_ref,
            }

    def recover(self, operation_id):
        """Conservative recovery: an interrupted backup/upgrade returns to the old release.

        The write gate remains closed until the durable recovery outcome is committed.
        Repeated recovery is safe because admitted input cannot occur in between.
        """
        import json
        from .backup import restore_original

        with host_lock(self.name):
            doc = self.journal.read(self.name)
            if not doc or doc["operation"]["id"] != operation_id:
                raise Conflict("wrong recovery operation")
            operation = doc["operation"]
            if operation["status"] == "completed":
                return {
                    "operation_id": operation_id,
                    "outcome": operation.get("outcome"),
                    "already_terminal": True,
                }
            if operation["kind"] not in ["backup", "upgrade"]:
                raise Conflict("use resume-install for installation")
            recorded = {
                k: v for k, v in operation["manifest"].items() if k != "candidate_image"
            }
            if recorded != asdict(self.manifest):
                raise Conflict("original manifest required for recovery")
            self.journal.recovery_intent(self.name, operation_id)
            self.storage.db.mesops_installations.update_one(
                {"_id": self.name}, {"$set": {"state": "maintenance"}}
            )
            steps = {s["name"]: s for s in operation["steps"]}
            backup_step = steps.get("backup", {})
            snapshot = None
            if backup_step.get("status") == "verified":
                snapshot = json.loads(self.storage.read(backup_step["evidence_ref"]))
            candidate_started = steps.get("candidate", {}).get("status") in [
                "running",
                "uncertain",
                "verified",
            ]
            if candidate_started and snapshot is None:
                raise Conflict("missing backup after candidate intent; do not guess")
            existing = Docker().container(self.manifest.container("app"))
            if existing is None and snapshot is None:
                raise Conflict("missing original application before verified backup")
            if existing:
                self.stack.require_owned("app")
                self.stack.command(
                    [
                        "stop",
                        "--time",
                        str(self.manifest.drain_seconds),
                        self.manifest.container("app"),
                    ]
                )
            RestoreResources(self.stack, self.storage, operation_id).reconcile()
            if snapshot:
                data = self.storage.read(snapshot["backup_ref"])
                verify_restore(
                    self.stack,
                    data,
                    snapshot["checksum"],
                    snapshot["fingerprint"],
                    RestoreResources(self.stack, self.storage, operation_id),
                )
                restore_original(
                    self.stack, data, snapshot["checksum"], snapshot["fingerprint"]
                )
            elif (
                existing
                and existing["Image"]
                != Docker().image(self.manifest.application_image)["Id"]
            ):
                raise Conflict("unexpected image before verified backup")
            if existing:
                self.stack.command(["rm", self.manifest.container("app")])
            self.stack.create_app()
            self.stack.wait_application()
            if snapshot and fingerprint(self.stack) != snapshot["fingerprint"]:
                raise RuntimeError("recovered database differs from baseline")
            self.semantic_probe(operation_id)
            evidence = {
                "outcome": "rolled_back",
                "original_image": Docker().image(self.manifest.application_image)["Id"],
                "backup_restored": bool(snapshot),
                "api_verified": True,
                "operation_id": operation_id,
            }
            ref = self.storage.evidence(evidence)
            self.storage.db.mesops_installations.update_one(
                {"_id": self.name},
                {"$set": {"state": "ready", "manifest": asdict(self.manifest)}},
            )
            self.journal.recovered(self.name, operation_id, ref)
            return {
                "operation_id": operation_id,
                "outcome": "rolled_back",
                "evidence_ref": ref,
            }
