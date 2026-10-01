"""Disposable acceptance only: dependency faults and sanitized support evidence."""

import json

from .control.backup import fingerprint
from .control.diagnostics import support_bundle


def exercise(controller):
    stack = controller.stack
    before = fingerprint(stack)
    reports = {}

    def collect(label, required=()):
        bundle = support_bundle(controller)
        report = bundle["report"]
        serialized = json.dumps(report, sort_keys=True)
        if stack.password in serialized:
            raise AssertionError("credential leaked into support report")
        if any(
            token in serialized
            for token in ["DATABASE_PASSWORD", "response_body", "POSTGRES_PASSWORD"]
        ):
            raise AssertionError("private environment or payload included")
        if not set(required).issubset(report["findings"]):
            raise AssertionError("dependency fault not diagnosed")
        reports[label] = bundle
        return report

    healthy = collect("healthy")
    if healthy["findings"] or healthy.get("readiness") != "UP":
        raise AssertionError("healthy installation misdiagnosed")
    if fingerprint(stack) != before:
        raise AssertionError("read-only diagnosis changed records")
    for role, findings in [
        ("cache", ["cache_not_running", "cache_unavailable"]),
        ("database", ["database_not_running"]),
    ]:
        stack.require_owned(role)
        stack.command(["stop", "--time", "10", controller.manifest.container(role)])
        try:
            collect(role + "_stopped", findings)
        finally:
            stack.command(["start", controller.manifest.container(role)])
            stack.wait_database()
            if role == "database":
                mismatch = collect("database_restarted")
                if "dependency_namespace_mismatch" not in mismatch["findings"]:
                    raise AssertionError("expected namespace mismatch not observed")
                # Docker network-container peers can retain the old namespace
                # when the namespace owner restarts. Reattach only these owned
                # disposable peers; authoritative DB volume is untouched.
                for peer in ["app", "cache"]:
                    stack.require_owned(peer)
                    stack.command(
                        ["stop", "--time", "10", controller.manifest.container(peer)]
                    )
                    stack.command(["rm", controller.manifest.container(peer)])
                stack.create_cache()
                stack.create_app()
            stack.wait_application()
    recovered = collect("recovered")
    if recovered["findings"] or recovered.get("readiness") != "UP":
        raise AssertionError("dependencies did not recover")
    if fingerprint(stack) != before:
        raise AssertionError("dependency fault exercise changed records")
    return {
        "reports": reports,
        "records_preserved": True,
        "credential_absent": True,
        "scope": "disposable reference stack dependency faults",
    }
