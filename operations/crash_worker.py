"""Acceptance-only worker killed by SIGKILL at a selected real upgrade boundary."""

import json
import os
import signal
import sys
from .control.controller import Controller
from .control.manifest import Manifest
from .control.storage import Storage


def main():
    config = json.load(sys.stdin)
    stage = config["stage"]
    if stage not in [
        "backup",
        "restore-created",
        "install-database",
        "candidate-start",
        "candidate",
        "decision",
        "service",
    ]:
        raise ValueError("unknown crash stage")
    c = Controller(
        Manifest.parse(config["manifest"]), config["password"], Storage.environment()
    )
    original = c._verified

    def verified(op, step, evidence):
        result = original(op, step, evidence)
        if step == stage or (stage == "install-database" and step == "database"):
            os.kill(os.getpid(), signal.SIGKILL)
        return result

    c._verified = verified
    start = c.stack.create_app

    def create(image=None):
        result = start(image)
        if stage == "candidate-start":
            os.kill(os.getpid(), signal.SIGKILL)
        return result

    c.stack.create_app = create
    command = c.stack.command

    def crash_after_create(args, **kwargs):
        result = command(args, **kwargs)
        if (
            stage == "restore-created"
            and "createdb" in args
            and args[-1].startswith("mes_restore_")
        ):
            os.kill(os.getpid(), signal.SIGKILL)
        return result

    c.stack.command = crash_after_create
    if stage == "install-database":
        c.install()
    else:
        c.upgrade(config["candidate"])
    raise RuntimeError("crash boundary was not reached")


if __name__ == "__main__":
    main()
