"""Real PostgreSQL backup corruption and restore refusal acceptance."""

import hashlib
import json
from .control.backup import fingerprint, identifier, verify_restore


def exercise(controller):
    stack = controller.stack
    stack.stop_app()
    try:
        expected = fingerprint(stack)
        backup, checksum = stack.dump()
        checks = []
        cases = [
            ("checksum_corrupt", backup + b"changed", checksum),
            (
                "invalid_archive",
                b"PGDMPbroken",
                hashlib.sha256(b"PGDMPbroken").hexdigest(),
            ),
        ]
        for name, data, digest in cases:
            try:
                verify_restore(stack, data, digest, expected)
            except (ValueError, RuntimeError):
                checks.append({"case": name, "rejected": True})
            else:
                raise AssertionError("corrupt backup accepted")
        original_command = stack.command

        def alter_restored_sequence(args, **kwargs):
            result = original_command(args, **kwargs)
            if "pg_restore" in args:
                scratch = args[args.index("-d") + 1]
                names = json.loads(
                    stack.sql(
                        "SELECT json_agg(sequencename ORDER BY sequencename) FROM pg_sequences WHERE schemaname='public';",
                        database=scratch,
                    )
                )
                name = names[0]
                # Preserve last_value but change the next generated ID.
                relation = "public." + identifier(name)
                literal = relation.replace("'", "''")
                stack.sql(
                    f"SELECT setval('{literal}', (SELECT last_value FROM {relation}), false);",
                    database=scratch,
                )
            return result

        stack.command = alter_restored_sequence
        try:
            try:
                verify_restore(stack, backup, checksum, expected)
            except RuntimeError:
                checks.append({"case": "restored_sequence_changed", "rejected": True})
            else:
                raise AssertionError("sequence divergence accepted")
        finally:
            stack.command = original_command
        verified = verify_restore(stack, backup, checksum, expected)
        if not verified["verified"] or fingerprint(stack) != expected:
            raise AssertionError("source changed or valid backup rejected")
        scratch_count = int(
            stack.sql(
                "SELECT count(*) FROM pg_database WHERE datname LIKE 'mes_restore_%';"
            )
        )
        if scratch_count:
            raise AssertionError("scratch databases leaked after restore failures")
        return {
            "refusal_checks": checks,
            "valid_restore": True,
            "source_unchanged": True,
            "scratch_databases": scratch_count,
        }
    finally:
        stack.command(["start", controller.manifest.container("app")])
        stack.wait_application()
