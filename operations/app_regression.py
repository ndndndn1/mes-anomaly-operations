"""Run the repository's black-box tests inside an isolated managed installation."""

import io
import json
from pathlib import Path
import tarfile
import time
from .control.manifest import LABEL
from .control.preflight import Docker

RUNNER = """import os, subprocess, sys, time, urllib.request
children=[]
try:
 for role, port in [('sensor',8082),('plc',8083),('verifier',8084)]:
  children.append(subprocess.Popen([sys.executable,'/tests/mocks/server.py'],env={**os.environ,'MOCK_ROLE':role,'MOCK_PORT':str(port)}))
  deadline=time.monotonic()+20
  while True:
   try:
    urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/health',timeout=1).close()
    break
   except OSError:
    if time.monotonic()>deadline: raise
    time.sleep(.1)
 subprocess.run([sys.executable,'/tests/integration.py'],check=True,timeout=120)
finally:
 for child in children: child.terminate()
 for child in children: child.wait(timeout=10)
"""


def exercise(controller):
    stack = controller.stack
    helper_image = Docker().image("mes-anomaly-operations-integration-test:latest")[
        "Id"
    ]
    fallback = "mesops-" + controller.name + "-regression-app"
    client = "mesops-" + controller.name + "-regression-client"
    created = []

    def create(name, image, env, command, memory):
        if Docker().container(name) is not None:
            raise RuntimeError("regression helper identity already exists")
        stack.command(
            [
                "create",
                "--name",
                name,
                "--label",
                f"{LABEL}={controller.name}",
                "--network",
                "container:" + controller.manifest.container("database"),
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                memory,
                "--cpus",
                "1",
                "--pids-limit",
                "256",
                "--env-file",
                "/dev/stdin",
                image,
                *command,
            ],
            data="".join(f"{k}={v}\n" for k, v in env.items()).encode(),
        )
        created.append(name)

    try:
        create(
            fallback,
            controller.manifest.application_image,
            {
                "DATABASE_URL": "jdbc:postgresql://127.0.0.1:5432/mes",
                "DATABASE_USER": "mes",
                "DATABASE_PASSWORD": stack.password,
                "REDIS_HOST": "127.0.0.1",
                "REDIS_PORT": "6399",
                "SERVER_PORT": "8081",
                "TEST_FAILURE_INJECTION_ENABLED": "true",
                "MANAGEMENT_HEALTH_REDIS_ENABLED": "false",
                "JAVA_TOOL_OPTIONS": "-XX:MaxRAMPercentage=60 -XX:+ExitOnOutOfMemoryError",
            },
            [],
            "768m",
        )
        stack.command(["start", fallback])
        deadline = time.monotonic() + 120
        while True:
            try:
                health = json.loads(
                    stack.command(
                        [
                            "exec",
                            controller.manifest.container("app"),
                            "curl",
                            "--silent",
                            "--fail",
                            "--max-time",
                            "3",
                            "http://127.0.0.1:8081/actuator/health",
                        ],
                        timeout=5,
                    )
                )
                if health.get("status") == "UP":
                    break
            except RuntimeError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("fallback application did not become ready")
            time.sleep(0.5)
        create(
            client,
            helper_image,
            {
                "API_URL": "http://127.0.0.1:8080",
                "FALLBACK_API_URL": "http://127.0.0.1:8081",
                "SENSOR_MOCK_URL": "http://127.0.0.1:8082",
                "PLC_MOCK_URL": "http://127.0.0.1:8083",
                "VERIFIER_MOCK_URL": "http://127.0.0.1:8084",
            },
            ["python", "/tests/regression_runner.py"],
            "256m",
        )
        root = Path(__file__).resolve().parents[1]
        files = {
            "integration.py": (root / "test/integration.py").read_bytes(),
            "mocks/server.py": (root / "test/mocks/server.py").read_bytes(),
            "regression_runner.py": RUNNER.encode(),
        }
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(content))
        stack.command(["cp", "-", client + ":/tests"], data=stream.getvalue())
        output = stack.command(["start", "-a", client], timeout=180).decode()
        state = Docker().container(client)["State"]
        if (
            state["ExitCode"]
            or "MES integration, concurrency, rollback, Redis fallback, and mock checks passed"
            not in output
        ):
            raise RuntimeError("black-box application regression failed")
        return {
            "passed": True,
            "test_image": helper_image,
            "checks": [
                "HTTP contracts",
                "idempotent concurrency",
                "transaction rollback",
                "Redis fallback",
                "mock integrations",
                "metrics",
            ],
        }
    finally:
        for name in reversed(created):
            data = Docker().container(name)
            if data is not None:
                if not controller.manifest.owns(data):
                    raise RuntimeError("regression helper ownership changed")
                stack.command(["rm", "-f", name])
