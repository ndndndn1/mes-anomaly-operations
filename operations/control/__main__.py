import argparse
import json
import os
import sys
from .manifest import Manifest
from .preflight import inspect


def main():
    parser = argparse.ArgumentParser(description="Manufacturing application operations")
    parser.add_argument(
        "command",
        choices=[
            "inspect",
            "install",
            "backup",
            "status",
            "resume-install",
            "recover",
            "diagnose",
            "support-bundle",
            "upgrade",
            "evaluate",
            "replay",
        ],
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Explicit immutable deployment contract, no secrets",
    )
    parser.add_argument("--operation-id")
    parser.add_argument("--candidate-image")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    with open(args.manifest) as source:
        manifest = Manifest.parse(json.load(source))
    if args.command == "inspect":
        result = inspect(manifest)
    else:
        from .storage import Storage
        from .controller import Controller

        password = os.environ.get("MESOPS_DATABASE_PASSWORD", "")
        if not password:
            raise ValueError("MESOPS_DATABASE_PASSWORD required; never pass in argv")
        controller = Controller(manifest, password, Storage.environment())
        if args.command == "resume-install":
            if not args.operation_id:
                raise ValueError("exact operation ID required")
            result = controller.install(resume=args.operation_id)
        elif args.command == "recover":
            if not args.operation_id:
                raise ValueError("exact operation ID required")
            result = controller.recover(args.operation_id)
        elif args.command in ("diagnose", "support-bundle"):
            from .diagnostics import diagnose, support_bundle

            result = (
                diagnose(controller)
                if args.command == "diagnose"
                else support_bundle(controller)
            )
        elif args.command == "upgrade":
            if not args.candidate_image:
                raise ValueError("candidate image required")
            result = controller.upgrade(args.candidate_image)
        elif args.command == "evaluate":
            result = controller.evaluate(json.load(sys.stdin))
        elif args.command == "replay":
            result = controller.replay(args.limit)
        else:
            result = getattr(controller, args.command)()
    print(json.dumps(result, indent=2))
    if result.get("rejected") is True:
        return 2
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
