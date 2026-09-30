"""Run an offline PostgreSQL rehearsal. Never connects to an existing database."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from contextlib import contextmanager


def execute(args, *, data=None, check=True):
    return subprocess.run(
        args, input=data, text=True, capture_output=True, timeout=40, check=check
    )


@contextmanager
def database():
    # No ports, no host data mounts, no shared networks, no persistent volumes.
    name = "mes-rehearsal-" + uuid.uuid4().hex[:12]
    image = execute(
        ["docker", "image", "inspect", "postgres:17-alpine", "--format", "{{.Id}}"]
    ).stdout.strip()
    execute(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/var/lib/postgresql/data:rw,nosuid,size=128m,uid=70,gid=70,mode=0700",
            "--tmpfs",
            "/var/run/postgresql:rw,nosuid,size=8m,uid=70,gid=70,mode=0700",
            "--tmpfs",
            "/tmp:rw,nosuid,size=8m",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "64",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            "postgres",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            image,
        ]
    )
    try:
        for _ in range(40):
            r = execute(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"], check=False
            )
            if (
                r.returncode == 0
                and execute(
                    ["docker", "exec", name, "cat", "/proc/1/comm"], check=False
                ).stdout.strip()
                == "postgres"
            ):
                yield name, image
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(
                "isolated database did not become ready: "
                + execute(["docker", "logs", name], check=False).stderr[-1800:]
            )
    finally:
        execute(["docker", "rm", "-f", name], check=False)


def sql(name, query, *, check=True):
    return execute(
        [
            "docker",
            "exec",
            "-i",
            name,
            "psql",
            "-X",
            "-q",
            "-A",
            "-t",
            "-U",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        data=query,
        check=check,
    )


def signature(name):
    return sql(
        name,
        "SELECT md5(string_agg(id::text||':'||value,',' ORDER BY id)) FROM readings;",
    ).stdout.strip()


def reset(name):
    sql(
        name,
        "DROP TABLE IF EXISTS readings; CREATE TABLE readings(id integer PRIMARY KEY,value text NOT NULL); INSERT INTO readings VALUES(1,'synthetic-A'),(2,'synthetic-B');",
    )


def run():
    results = []
    with database() as (name, image):
        for transactional in (False, True):
            for fault in (
                "none",
                "invalid_sql",
                "lock_timeout",
                "duplicate_key",
                "disconnect",
            ):
                reset(name)
                original = signature(name)
                started = time.monotonic()
                prefix = (
                    "BEGIN; SET LOCAL lock_timeout='300ms';"
                    if transactional
                    else "SET lock_timeout='300ms';"
                )
                lock = None
                try:
                    if fault == "lock_timeout":
                        lock = subprocess.Popen(
                            [
                                "docker",
                                "exec",
                                "-i",
                                name,
                                "psql",
                                "-X",
                                "-q",
                                "-U",
                                "postgres",
                            ],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            text=True,
                        )
                        lock.stdin.write(
                            "BEGIN; LOCK TABLE readings IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(10); ROLLBACK;\n"
                        )
                        lock.stdin.close()
                        for _ in range(40):
                            locked = sql(
                                name,
                                "SELECT count(*) FROM pg_locks WHERE relation='readings'::regclass AND mode='AccessExclusiveLock' AND granted;",
                            ).stdout.strip()
                            if locked == "1":
                                break
                            time.sleep(0.025)
                        else:
                            raise RuntimeError("fault setup not confirmed")
                    changes = "ALTER TABLE readings ADD COLUMN quality integer DEFAULT 1; UPDATE readings SET value='upgraded' WHERE id=1;"
                    suffix = {
                        "none": "",
                        "invalid_sql": "SELECT missing_column FROM readings;",
                        "duplicate_key": "INSERT INTO readings VALUES(1,'duplicate',1);",
                        "lock_timeout": "",
                        "disconnect": "SELECT pg_terminate_backend(pg_backend_pid());",
                    }[fault]
                    r = sql(
                        name,
                        prefix
                        + changes
                        + suffix
                        + ("COMMIT;" if transactional else ""),
                        check=False,
                    )
                finally:
                    if lock:
                        sql(
                            name,
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid<>pg_backend_pid() AND query LIKE '%pg_sleep(10)%';",
                        )
                        lock.wait(timeout=5)
                columns = sql(
                    name,
                    "SELECT count(*) FROM information_schema.columns WHERE table_name='readings' AND column_name='quality';",
                ).stdout.strip()
                unchanged = signature(name) == original and columns == "0"
                success = (
                    r.returncode == 0
                    and columns == "1"
                    and sql(
                        name, "SELECT value||':'||quality FROM readings WHERE id=1;"
                    ).stdout.strip()
                    == "upgraded:1"
                )
                expected = (
                    success if fault == "none" else r.returncode != 0 and unchanged
                )
                results.append(
                    {
                        "mode": "transactional"
                        if transactional
                        else "autocommit_baseline",
                        "fault": fault,
                        "passed": expected,
                        "returncode": r.returncode,
                        "original_preserved": unchanged,
                        "seconds": round(time.monotonic() - started, 4),
                    }
                )
    return {
        "scope": "isolated synthetic PostgreSQL; not Klarity, Oracle, or production validation",
        "image_id": image,
        "scenarios": results,
        "transactional_passed": sum(
            r["passed"] for r in results if r["mode"] == "transactional"
        ),
        "transactional_total": 5,
        "baseline_passed": sum(
            r["passed"] for r in results if r["mode"] == "autocommit_baseline"
        ),
        "baseline_total": 5,
        "unexecuted": [
            "Klarity KD/ACE upgrade",
            "Oracle/PL-SQL compatibility",
            "customer production rollout",
        ],
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    raise SystemExit(
        0 if result["transactional_passed"] == result["transactional_total"] else 1
    )
