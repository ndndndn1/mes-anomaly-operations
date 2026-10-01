"""Read-only inventory. Never return Docker Env or raw inspect output."""

import json
import os
from pathlib import Path
import subprocess
from .manifest import Manifest


class Docker:
    def run(self, *args):
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=20
        )
        if result.returncode:
            # Docker error strings may contain private command arguments or registry URLs.
            raise RuntimeError("docker inspection failed")
        return result.stdout

    def resources(self):
        endpoint = (
            os.environ.get("DOCKER_HOST")
            or self.run(
                "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
            ).strip()
        )
        if not endpoint.startswith("unix://"):
            raise RuntimeError("resource admission requires a local Docker engine")
        info = json.loads(self.run("info", "--format", "{{json .}}"))
        memory = next(
            int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        disk = os.statvfs(info["DockerRootDir"])
        return {
            "memory_available_bytes": memory,
            "storage_available_bytes": disk.f_bavail * disk.f_frsize,
            "cpus": info["NCPU"],
        }

    def image(self, ref):
        return json.loads(self.run("image", "inspect", ref))[0]

    def container(self, name):
        # Query existence separately: inspection failure is NOT treated as absence.
        ids = self.run("ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}")
        if not ids.strip():
            return None
        if len(ids.splitlines()) != 1:
            raise RuntimeError("ambiguous container identity")
        return json.loads(self.run("inspect", name))[0]


def inspect(manifest: Manifest, docker=None):
    docker = docker or Docker()
    checks = []
    try:
        resources = docker.resources()
        checks.append(
            {
                "check": "host.resources",
                "ok": resources["memory_available_bytes"] >= 2 * 1024**3
                and resources["storage_available_bytes"] >= 2 * 1024**3
                and resources["cpus"] >= 1,
                "observed": resources,
                "minimum_memory_bytes": 2 * 1024**3,
                "minimum_storage_bytes": 2 * 1024**3,
                "reason": "point-in-time admission check; not a reservation or capacity SLA",
            }
        )
    except (
        RuntimeError,
        OSError,
        KeyError,
        ValueError,
        StopIteration,
        subprocess.TimeoutExpired,
    ):
        checks.append(
            {
                "check": "host.resources",
                "ok": False,
                "reason": "local capacity unavailable; do not install",
            }
        )
    for role, ref in (
        ("app", manifest.application_image),
        ("database", manifest.database_image),
        ("cache", manifest.cache_image),
    ):
        try:
            image = docker.image(ref)
            if role == "database":
                # Official PostgreSQL images declare PG_MAJOR. Refuse missing,
                # conflicting or incompatible metadata before installation creates
                # a journal, volume or container. Runtime readiness still checks
                # the actual server version; metadata is not a substitute for it.
                declared = [
                    item.partition("=")[2]
                    for item in (image.get("Config", {}).get("Env") or [])
                    if isinstance(item, str) and item.startswith("PG_MAJOR=")
                ]
                checks.append(
                    {
                        "check": "database.image_major",
                        "ok": declared == [str(manifest.database_major)],
                        "expected_major": manifest.database_major,
                        "reason": "image must unambiguously declare supported PostgreSQL major",
                    }
                )
            checks.append(
                {
                    "check": f"{role}.image",
                    "ok": True,
                    "image_id": image["Id"],
                    "architecture": image.get("Architecture"),
                }
            )
        except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired):
            checks.append(
                {
                    "check": f"{role}.image",
                    "ok": False,
                    "reason": "local image unavailable or inspection failed",
                }
            )
        try:
            container = docker.container(manifest.container(role))
            owned = container is None or manifest.owns(container)
            checks.append(
                {
                    "check": f"{role}.ownership",
                    "ok": owned,
                    "exists": container is not None,
                    "reason": "available"
                    if container is None
                    else "managed"
                    if owned
                    else "unmanaged target: refuse mutation",
                }
            )
        except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired):
            checks.append(
                {
                    "check": f"{role}.ownership",
                    "ok": False,
                    "reason": "inventory unavailable; not assumed absent",
                }
            )
    return {
        "stage": "inventory",
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "limitations": [
            "not a deployment approval",
            "database engine and readiness not yet checked",
            "no mutation performed",
        ],
    }
