"""Managed reference stack. All services share a network-none namespace.

No host port, host data mount, Docker socket, or WAN access is given to workloads.
Passwords travel on stdin and are never included in the returned evidence.
"""

import hashlib
import json
import subprocess
import time
from .manifest import LABEL


class InputRejected(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Application rejected input with HTTP {status}")


class Stack:
    def __init__(self, manifest, password):
        if not password or "\n" in password or "\r" in password:
            raise ValueError("single-line database credential required")
        self.manifest = manifest
        self.password = password
        self.volume = f"mesops-{manifest.installation}-database"

    def command(self, args, data=None, timeout=60):
        result = subprocess.run(
            ["docker", *args], input=data, capture_output=True, timeout=timeout
        )
        if result.returncode:
            raise RuntimeError("Docker operation failed; collect sanitized diagnostics")
        return result.stdout

    def require_owned(self, role):
        name = self.manifest.container(role)
        data = json.loads(self.command(["inspect", name]))[0]
        if not self.manifest.owns(data):
            raise RuntimeError("unmanaged container refused")
        return data

    def create_database(self, reuse_owned_volume=False):
        # A preexisting volume must also be owned; never adopt by name alone.
        names = (
            self.command(["volume", "ls", "--format", "{{.Name}}"])
            .decode()
            .splitlines()
        )
        if self.volume in names:
            volume = json.loads(self.command(["volume", "inspect", self.volume]))[0]
            if (
                not reuse_owned_volume
                or (volume.get("Labels") or {}).get(LABEL) != self.manifest.installation
            ):
                raise RuntimeError("existing volume: reconcile, do not reinstall")
        self.command(
            [
                "volume",
                "create",
                "--label",
                f"{LABEL}={self.manifest.installation}",
                self.volume,
            ]
        )
        self._start(
            "database",
            self.manifest.database_image,
            [
                "--network",
                "none",
                "--user",
                "postgres",
                "--mount",
                f"type=volume,src={self.volume},dst=/var/lib/postgresql/data",
                "--tmpfs",
                "/var/run/postgresql:rw,nosuid,size=8m,uid=70,gid=70,mode=0700",
            ],
            {
                "POSTGRES_DB": "mes",
                "POSTGRES_USER": "mes",
                "POSTGRES_PASSWORD": self.password,
            },
        )

    def _start(self, role, image, options, environment, command=()):
        env = "".join(f"{key}={value}\n" for key, value in environment.items()).encode()
        self.command(
            [
                "run",
                "-d",
                "--name",
                self.manifest.container(role),
                "--label",
                f"{LABEL}={self.manifest.installation}",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "768m" if role == "app" else "512m",
                "--cpus",
                "1",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/tmp:rw,nosuid,size=64m",
                *options,
                "--env-file",
                "/dev/stdin",
                image,
                *command,
            ],
            data=env,
        )

    def create_cache(self):
        self.require_owned("database")
        self._start(
            "cache",
            self.manifest.cache_image,
            [
                "--network",
                "container:" + self.manifest.container("database"),
                "--user",
                "redis",
            ],
            {},
            [
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
                "--maxmemory",
                "64mb",
                "--maxmemory-policy",
                "allkeys-lru",
            ],
        )

    def create_app(self, image=None):
        self.require_owned("database")
        self.require_owned("cache")
        self._start(
            "app",
            image or self.manifest.application_image,
            ["--network", "container:" + self.manifest.container("database")],
            {
                "DATABASE_URL": "jdbc:postgresql://127.0.0.1:5432/mes",
                "DATABASE_USER": "mes",
                "DATABASE_PASSWORD": self.password,
                "REDIS_HOST": "127.0.0.1",
                "JAVA_TOOL_OPTIONS": "-XX:MaxRAMPercentage=60 -XX:+ExitOnOutOfMemoryError",
            },
        )

    def sql(self, query, timeout=30, database="mes"):
        if database != "mes" and not database.startswith("mes_restore_"):
            raise ValueError("unexpected database")
        self.require_owned("database")
        return self.command(
            [
                "exec",
                "-i",
                self.manifest.container("database"),
                "psql",
                "-X",
                "-q",
                "-A",
                "-t",
                "-U",
                "mes",
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
            ],
            data=query.encode(),
            timeout=timeout,
        )

    def api(self, path, payload=None):
        if path not in ["/actuator/health", "/api/v1/evaluations"]:
            raise ValueError("unsupported API path")
        self.require_owned("app")
        args = [
            "exec",
            "-i",
            self.manifest.container("app"),
            "curl",
            "--silent",
            "--show-error",
            "--write-out",
            "\n%{http_code}",
            "--max-time",
            "10",
            "http://127.0.0.1:8080" + path,
        ]
        data = None
        if payload is not None:
            args += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
            data = json.dumps(payload, allow_nan=False).encode()
        raw = self.command(args, data=data, timeout=15)
        body, code = raw.rsplit(b"\n", 1)
        status = int(code)
        if payload is not None and status in {400, 409, 413, 415, 422}:
            raise InputRejected(status)
        if status not in {200, 201}:
            raise RuntimeError(
                f"Application unavailable or outcome uncertain: HTTP {status}"
            )
        return json.loads(body)

    def wait_database(self):
        deadline = time.monotonic() + self.manifest.readiness_seconds
        while time.monotonic() < deadline:
            try:
                pid = (
                    self.command(
                        [
                            "exec",
                            self.manifest.container("database"),
                            "cat",
                            "/proc/1/comm",
                        ]
                    )
                    .decode()
                    .strip()
                )
                version = int(self.sql("SHOW server_version_num;").decode().strip())
                if (
                    pid == "postgres"
                    and version // 10000 == self.manifest.database_major
                ):
                    return version
            except (RuntimeError, ValueError):
                pass
            time.sleep(0.5)
        raise RuntimeError("database readiness deadline exceeded")

    def wait_application(self):
        deadline = time.monotonic() + self.manifest.readiness_seconds
        while time.monotonic() < deadline:
            if not self.require_owned("app")["State"]["Running"]:
                raise RuntimeError("application exited before readiness")
            try:
                if self.api("/actuator/health").get("status") == "UP":
                    return
            except (RuntimeError, ValueError):
                pass
            time.sleep(0.5)
        raise RuntimeError("application readiness deadline exceeded")

    def dump(self):
        self.require_owned("database")
        data = self.command(
            [
                "exec",
                self.manifest.container("database"),
                "pg_dump",
                "-U",
                "mes",
                "-d",
                "mes",
                "-Fc",
                "--no-owner",
                "--no-acl",
            ],
            timeout=120,
        )
        if not data.startswith(b"PGDMP"):
            raise RuntimeError("invalid backup format")
        return data, hashlib.sha256(data).hexdigest()

    def stop_app(self):
        self.require_owned("app")
        self.command(
            [
                "stop",
                "--time",
                str(self.manifest.drain_seconds),
                self.manifest.container("app"),
            ]
        )
        if self.require_owned("app")["State"]["Running"]:
            raise RuntimeError("application not drained")
        # All writes to this reference DB originate from the one controlled app.
        count = int(
            self.sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname='mes' AND pid<>pg_backend_pid() AND backend_type='client backend';"
            ).decode()
        )
        if count:
            raise RuntimeError(
                "other database clients prevent consistent maintenance boundary"
            )

    def destroy(self):
        # Explicitly called only for an owned disposable installation, never error auto-cleanup.
        for role in ["app", "cache", "database"]:
            name = self.manifest.container(role)
            matches = (
                self.command(
                    ["ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"]
                )
                .decode()
                .strip()
            )
            if matches:
                self.require_owned(role)
                self.command(["rm", "-f", name])
        data = json.loads(self.command(["volume", "inspect", self.volume]))[0]
        if (data.get("Labels") or {}).get(LABEL) != self.manifest.installation:
            raise RuntimeError("unmanaged volume refused")
        self.command(["volume", "rm", self.volume])
