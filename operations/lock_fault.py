"""Acceptance-only transaction lock, restricted to the disposable managed stack."""

from contextlib import contextmanager
import subprocess
import time
import uuid


@contextmanager
def candidate_lock(controller, candidate):
    stack = controller.stack
    original_create = stack.create_app
    original_wait = stack.wait_application
    owner = "mesops_fault_" + uuid.uuid4().hex
    process = None
    observed = {"lock_confirmed": False}

    def release():
        nonlocal process
        if process is not None:
            # Terminate only our uniquely named synthetic transaction, never
            # arbitrary application/other operator sessions.
            stack.sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='"
                + owner
                + "';"
            )
            process.communicate(timeout=10)
            process = None

    def create(image=None):
        nonlocal process
        if image == candidate:
            stack.require_owned("database")
            process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    controller.manifest.container("database"),
                    "psql",
                    "-X",
                    "-q",
                    "-U",
                    "mes",
                    "-d",
                    "mes",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process.stdin.write(
                (
                    "SET application_name='"
                    + owner
                    + "'; BEGIN; LOCK TABLE evaluation_event IN ACCESS EXCLUSIVE MODE;\n"
                ).encode()
            )
            process.stdin.flush()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                count = int(
                    stack.sql(
                        "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON l.pid=a.pid WHERE a.application_name='"
                        + owner
                        + "' AND l.relation='evaluation_event'::regclass AND l.mode='AccessExclusiveLock' AND l.granted;"
                    )
                )
                if count == 1:
                    observed["lock_confirmed"] = True
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("test lock not confirmed")
        return original_create(image)

    def wait():
        try:
            return original_wait()
        finally:
            release()

    stack.create_app = create
    stack.wait_application = wait
    try:
        yield observed
    finally:
        stack.create_app = original_create
        stack.wait_application = original_wait
        release()
