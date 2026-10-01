"""Real managed-stack refusal checks and public CLI inventory smoke."""

from dataclasses import asdict
import json
import subprocess
import sys
from unittest.mock import patch
from .control.controller import Controller
from .control.manifest import Manifest
from .control.preflight import Docker, inspect

from .control.backup import fingerprint
from .control.journal import host_lock


def exercise(controller, candidate):
    original = fingerprint(controller.stack)
    revision = controller.status()["revision"]
    checks = []
    try:
        controller.install()
    except RuntimeError:
        checks.append("duplicate_install_refused")
    else:
        raise AssertionError("duplicate installation accepted")
    with host_lock(controller.name):
        try:
            controller.upgrade(candidate)
        except BlockingIOError:
            checks.append("concurrent_upgrade_refused")
        else:
            raise AssertionError("concurrent upgrade accepted")
    for missing in [False, True]:
        manifest = asdict(controller.manifest)
        if missing:
            manifest["application_image"] = "sha256:" + "0" * 64
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "operations.control",
                "inspect",
                "--manifest",
                "/dev/stdin",
            ],
            input=json.dumps(manifest),
            text=True,
            capture_output=True,
            timeout=90,
        )
        report = json.loads(result.stdout)
        if report["ok"] == missing or result.returncode != (1 if missing else 0):
            raise AssertionError("public inventory CLI result mismatch")
        checks.append("missing_image_refused" if missing else "cli_inventory_passed")
    spare = Manifest.parse(
        {**asdict(controller.manifest), "installation": controller.name + "-capacity"}
    )
    if not inspect(spare)["ok"]:
        raise AssertionError("normal resource precondition failed")
    with patch.object(
        Docker,
        "resources",
        return_value={
            "memory_available_bytes": 1024,
            "storage_available_bytes": 4 * 1024**3,
            "cpus": 2,
        },
    ):
        refused = Controller(spare, controller.stack.password, controller.storage)
        try:
            refused.install()
        except RuntimeError:
            pass
        else:
            raise AssertionError("insufficient resources permitted installation")
    if any(
        Docker().container(spare.container(role)) is not None
        for role in ["app", "database", "cache"]
    ):
        raise AssertionError("resource refusal created containers")
    if controller.storage.db.mesops_journals.find_one({"_id": spare.installation}):
        raise AssertionError("resource refusal began a mutation journal")
    checks.append("injected_low_memory_refused_before_mutation")
    wrong_engine = Manifest.parse(
        {
            **asdict(controller.manifest),
            "installation": controller.name + "-engine",
            "database_image": controller.manifest.cache_image,
        }
    )
    invalid = Controller(wrong_engine, controller.stack.password, controller.storage)
    try:
        invalid.install()
    except RuntimeError:
        pass
    else:
        raise AssertionError("non-PostgreSQL image permitted installation")
    if any(
        Docker().container(wrong_engine.container(role)) is not None
        for role in ["app", "database", "cache"]
    ):
        raise AssertionError("engine refusal created containers")
    if controller.storage.db.mesops_journals.find_one(
        {"_id": wrong_engine.installation}
    ):
        raise AssertionError("engine refusal began a mutation journal")
    volumes = controller.stack.command(["volume", "ls", "--format", "{{.Name}}"])
    if invalid.stack.volume in volumes.decode().splitlines():
        raise AssertionError("engine refusal created a database volume")
    checks.append("wrong_database_image_refused_before_mutation")
    if (
        controller.status()["revision"] != revision
        or fingerprint(controller.stack) != original
    ):
        raise AssertionError("refused operation changed journal or database")
    return {"checks": checks, "journal_unchanged": True, "records_unchanged": True}
