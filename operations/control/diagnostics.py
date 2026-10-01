"""Bounded, read-only support evidence; no Env, customer rows or raw logs exported."""

import subprocess
import re
from .preflight import Docker

CODES = {
    "migration_failed": "FlywayMigrateException",
    "migration_validation_failed": "FlywayValidateException",
    "database_lock_timeout": "lock timeout",
    "database_authentication_failed": "password authentication failed",
    "connection_refused": "Connection refused",
    "invalid_detector_configuration": "window size must be between",
    "out_of_memory": "OutOfMemoryError",
}


def classify_logs(text):
    return sorted(code for code, needle in CODES.items() if needle in text)


def diagnose(controller):
    stack = controller.stack
    report = {
        "installation": controller.name,
        "operation": controller.status(),
        "components": {},
        "findings": [],
    }
    for role in ["database", "cache", "app"]:
        data = Docker().container(controller.manifest.container(role))
        if data is None:
            report["components"][role] = {"exists": False}
            report["findings"].append(role + "_missing")
            continue
        if not controller.manifest.owns(data):
            report["components"][role] = {"exists": True, "owned": False}
            report["findings"].append(role + "_unmanaged")
            continue
        state = data["State"]
        component = {
            "exists": True,
            "owned": True,
            "image_id": data["Image"],
            "status": state["Status"],
            "exit_code": state.get("ExitCode"),
            "oom_killed": state.get("OOMKilled"),
            "restart_count": data.get("RestartCount"),
            "memory_limit_bytes": data.get("HostConfig", {}).get("Memory"),
        }
        logs = subprocess.run(
            ["docker", "logs", "--tail", "100", controller.manifest.container(role)],
            capture_output=True,
            timeout=20,
        )
        component["log_codes"] = classify_logs(
            (logs.stdout + logs.stderr).decode(errors="replace")
        )
        if logs.returncode:
            component["log_collection"] = "unavailable"
        if state.get("OOMKilled"):
            report["findings"].append(role + "_oom")
        if not state["Running"]:
            report["findings"].append(role + "_not_running")
        if state["Running"]:
            try:
                namespace = (
                    stack.command(
                        [
                            "exec",
                            controller.manifest.container(role),
                            "readlink",
                            "/proc/1/ns/net",
                        ],
                        timeout=5,
                    )
                    .decode()
                    .strip()
                )
                if re.fullmatch(r"net:\[[0-9]+\]", namespace):
                    component["network_namespace"] = namespace
            except (RuntimeError, subprocess.TimeoutExpired):
                component["namespace_probe"] = "unavailable"
        report["components"][role] = component
    namespaces = {
        x["network_namespace"]
        for x in report["components"].values()
        if "network_namespace" in x
    }
    if len(namespaces) > 1:
        report["findings"].append("dependency_namespace_mismatch")
    db = report["components"]["database"]
    if db.get("owned") and db.get("status") == "running":
        try:
            report["database"] = {
                "version": stack.sql("SHOW server_version;").decode().strip(),
                "waiting_locks": int(
                    stack.sql(
                        "SELECT count(*) FROM pg_locks WHERE NOT granted;"
                    ).decode()
                ),
                "failed_migrations": int(
                    stack.sql(
                        "SELECT count(*) FROM flyway_schema_history WHERE NOT success;"
                    ).decode()
                ),
                "successful_versions": stack.sql(
                    "SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank;"
                )
                .decode()
                .splitlines(),
            }
            if report["database"]["waiting_locks"]:
                report["findings"].append("database_lock_contention")
            if report["database"]["failed_migrations"]:
                report["findings"].append("failed_migration_history")
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            report["findings"].append("database_probe_failed")
    if report["components"]["cache"].get("owned"):
        try:
            pong = (
                stack.command(
                    [
                        "exec",
                        controller.manifest.container("cache"),
                        "redis-cli",
                        "ping",
                    ]
                )
                .decode()
                .strip()
            )
            if pong != "PONG":
                raise RuntimeError("unexpected cache response")
        except (RuntimeError, subprocess.TimeoutExpired):
            report["findings"].append("cache_unavailable")
    if report["components"]["app"].get("owned"):
        try:
            report["readiness"] = stack.api("/actuator/health").get("status")
            if report["readiness"] != "UP":
                report["findings"].append("application_not_ready")
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            report["findings"].append("application_readiness_failed")
    suggestions = {
        "dependency_namespace_mismatch": "The database namespace owner restarted while peers retained an old namespace. Close ingress and preserve the database volume; recreate only the managed cache/application peers, then verify API readiness and records before reopening ingress.",
        "database_lock_contention": "Inspect transaction owners in the private database; do not kill sessions automatically.",
        "cache_unavailable": "Check managed cache process. Test authoritative API separately before concluding that data writes failed.",
        "database_probe_failed": "Check managed database readiness, schema version and configured credentials locally.",
        "application_readiness_failed": "Compare application image and migration/configuration error codes; do not retry an upgrade blindly.",
    }
    report["next_actions"] = [
        suggestions.get(
            code,
            "Inspect the named managed component and operation journal before changing it.",
        )
        for code in report["findings"]
    ]
    return report


def support_bundle(controller):
    report = diagnose(controller)
    # No payloads, raw logs, credentials, host paths, or environment are included.
    report["scope"] = "reference installation; not vendor product validation"
    report["reproduction"] = [
        "python3 -m operations.control " + command + " --manifest deployment.json"
        for command in ["inspect", "status", "diagnose"]
    ]
    journal = controller.journal.read(controller.name)
    if journal:
        operation = journal["operation"]
        report["operation_evidence_refs"] = {
            step["name"]: step["evidence_ref"]
            for step in operation["steps"]
            if re.fullmatch(r"[0-9a-f]{64}", step.get("evidence_ref", ""))
        }
        report["operation_started_at"] = str(operation["started_at"])
        report["operation_completed_at"] = str(operation.get("completed_at"))
    ref = controller.storage.evidence(report)
    return {"evidence_ref": ref, "report": report}
