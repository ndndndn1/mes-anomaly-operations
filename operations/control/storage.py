"""Scoped MongoDB/GridFS persistence, supplied by operator environment."""

import hashlib
import json
import os


class Storage:
    def __init__(self, database):
        from gridfs import GridFS

        self.db = database
        self.fs = GridFS(database, collection="mesops_blobs")

    @classmethod
    def environment(cls):
        from pymongo import MongoClient
        from pymongo.write_concern import WriteConcern

        uri = os.environ.get("MESOPS_MONGO_URI")
        name = os.environ.get("MESOPS_MONGO_DATABASE")
        if not uri or not name:
            raise ValueError("MESOPS_MONGO_URI and MESOPS_MONGO_DATABASE required")
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
            timeoutMS=15000,
        )
        db = client.get_database(
            name, write_concern=WriteConcern(w="majority", wtimeout=10000)
        )
        db.command("ping")
        return cls(db)

    def blob(self, data, kind):
        key = hashlib.sha256(data).hexdigest()
        if not self.fs.exists(key):
            try:
                self.fs.put(data, _id=key, filename=kind)
            except Exception:
                if not self.fs.exists(key):
                    raise
        if self.fs.get(key).read() != data:
            raise RuntimeError("blob verification failed")
        return key

    def evidence(self, data):
        return self.blob(
            json.dumps(data, sort_keys=True, default=str).encode(), "evidence.json"
        )

    def read(self, key):
        data = self.fs.get(key).read()
        if hashlib.sha256(data).hexdigest() != key:
            raise RuntimeError("stored blob digest mismatch")
        return data
