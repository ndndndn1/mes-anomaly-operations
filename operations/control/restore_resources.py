"""Durable ownership reservations for isolated restore databases.

Caller holds the installation's exclusive lock. Never delete by name prefix alone.
"""

from datetime import datetime, timezone
import re
import uuid


class RestoreResources:
    def __init__(self, stack, storage, operation_id):
        self.stack = stack
        self.collection = storage.db.mesops_restore_resources
        self.installation = stack.manifest.installation
        self.operation_id = operation_id

    def reserve(self):
        self.stack.require_owned("database")
        name = "mes_restore_" + uuid.uuid4().hex
        if int(
            self.stack.sql(
                "SELECT count(*) FROM pg_database WHERE datname='" + name + "';"
            )
        ):
            raise RuntimeError("restore database name already exists; do not adopt")
        self.collection.insert_one(
            {
                "_id": name,
                "installation": self.installation,
                "operation_id": self.operation_id,
                "state": "reserved",
                "created_at": datetime.now(timezone.utc),
            }
        )
        return name

    def cleaned(self, name):
        self.collection.update_one(
            {
                "_id": name,
                "installation": self.installation,
                "operation_id": self.operation_id,
            },
            {"$set": {"state": "cleaned", "cleaned_at": datetime.now(timezone.utc)}},
        )

    def reconcile(self):
        self.stack.require_owned("database")
        cleaned = []
        for row in self.collection.find(
            {
                "installation": self.installation,
                "operation_id": self.operation_id,
                "state": "reserved",
            }
        ):
            name = row["_id"]
            if not re.fullmatch(r"mes_restore_[0-9a-f]{32}", name):
                raise RuntimeError("invalid reserved restore identity")
            self.stack.command(
                [
                    "exec",
                    self.stack.manifest.container("database"),
                    "dropdb",
                    "-U",
                    "mes",
                    "--if-exists",
                    "--force",
                    name,
                ]
            )
            if int(
                self.stack.sql(
                    "SELECT count(*) FROM pg_database WHERE datname='" + name + "';"
                )
            ):
                raise RuntimeError("restore resource cleanup not verified")
            self.cleaned(name)
            cleaned.append(name)
        return cleaned
