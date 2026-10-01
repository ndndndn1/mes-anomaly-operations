"""A backup is usable only after an isolated restore and full record comparison."""

import hashlib
import json
import uuid


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def fingerprint(stack, database="mes"):
    result = {}
    tables = json.loads(
        stack.sql(
            "SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]'::json) FROM pg_tables WHERE schemaname='public';",
            database=database,
        )
    )
    if not tables:
        raise RuntimeError("no application tables to verify")
    for table in tables:
        # Stable multiset comparison retains duplicate rows, unlike DISTINCT or key counts.
        data = stack.sql(
            f'SELECT row_to_json(t)::text FROM public.{identifier(table)} t ORDER BY row_to_json(t)::text COLLATE "C";',
            database=database,
            timeout=120,
        )
        result[table] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "rows": len(data.splitlines()),
        }
    schema = stack.sql(
        "SELECT table_name,column_name,data_type,is_nullable,coalesce(column_default,'') FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position; SELECT conrelid::regclass,conname,pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conrelid::regclass::text,conname; SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname;",
        database=database,
    )
    result["schema_sha256"] = hashlib.sha256(schema).hexdigest()
    result["sequences_sha256"] = sequence_fingerprint(stack, database)
    return result


def sequence_fingerprint(stack, database="mes"):
    # last_value alone cannot distinguish setval(n, true) from setval(n, false).
    # Those states produce different next IDs after restoration.
    names = json.loads(
        stack.sql(
            "SELECT coalesce(json_agg(sequencename ORDER BY sequencename),'[]'::json) FROM pg_sequences WHERE schemaname='public';",
            database=database,
        )
    )
    states = []
    for name in names:
        value = (
            stack.sql(
                f"SELECT last_value,is_called FROM public.{identifier(name)};",
                database=database,
            )
            .decode()
            .strip()
        )
        states.append([name, value])
    metadata = stack.sql(
        "SELECT sequencename,data_type,start_value,min_value,max_value,increment_by,cycle,cache_size FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename;",
        database=database,
    ).decode()
    return hashlib.sha256(
        json.dumps([metadata, states], sort_keys=True).encode()
    ).hexdigest()


def verify_restore(stack, backup, checksum, expected, resources=None):
    if hashlib.sha256(backup).hexdigest() != checksum or not backup.startswith(
        b"PGDMP"
    ):
        raise ValueError("backup checksum/format mismatch: do not upgrade")
    scratch = (
        resources.reserve() if resources else "mes_restore_" + uuid.uuid4().hex[:12]
    )
    stack.require_owned("database")
    container = stack.manifest.container("database")
    stack.command(
        ["exec", container, "createdb", "-U", "mes", "--template", "template0", scratch]
    )
    try:
        stack.command(
            [
                "exec",
                "-i",
                container,
                "pg_restore",
                "-U",
                "mes",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "-d",
                scratch,
            ],
            data=backup,
            timeout=120,
        )
        restored = fingerprint(stack, scratch)
        if restored != expected:
            raise RuntimeError("restored schema/data differ: do not upgrade")
        return {"verified": True, "backup_sha256": checksum, "fingerprint": restored}
    finally:
        stack.command(["exec", container, "dropdb", "-U", "mes", scratch])
        if resources:
            resources.cleaned(scratch)


def restore_original(stack, backup, checksum, expected):
    """Destructive restore only inside the explicitly managed reference DB.

    Caller holds the exclusive installation lock and journals restoration intent.
    Backup must have passed isolated restoration before this function is invoked.
    """
    if hashlib.sha256(backup).hexdigest() != checksum:
        raise ValueError("backup integrity failure")
    from .preflight import Docker

    app = Docker().container(stack.manifest.container("app"))
    if app is not None:
        stack.require_owned("app")
    if app is not None and app["State"]["Running"]:
        raise RuntimeError("stop application before database restoration")
    stack.require_owned("database")
    container = stack.manifest.container("database")
    stack.command(["exec", container, "dropdb", "-U", "mes", "--if-exists", "mes"])
    stack.command(
        ["exec", container, "createdb", "-U", "mes", "--template", "template0", "mes"]
    )
    stack.command(
        [
            "exec",
            "-i",
            container,
            "pg_restore",
            "-U",
            "mes",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "-d",
            "mes",
        ],
        data=backup,
        timeout=120,
    )
    actual = fingerprint(stack)
    if actual != expected:
        raise RuntimeError("original database restoration verification failed")
    return actual
