"""Explicit deployment contract; reject mutable images and unrelated targets."""

from dataclasses import dataclass
import re

IMAGE = re.compile(r"^(?:sha256:[0-9a-f]{64}|[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64})$")
NAME = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
LABEL = "io.mesops.installation"


@dataclass(frozen=True)
class Manifest:
    installation: str
    application_image: str
    database_image: str
    cache_image: str
    database_major: int = 17
    drain_seconds: int = 30
    readiness_seconds: int = 120

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise ValueError("manifest must be an object")
        required = {
            "installation",
            "application_image",
            "database_image",
            "cache_image",
        }
        allowed = required | {"database_major", "drain_seconds", "readiness_seconds"}
        if not required <= value.keys() or value.keys() - allowed:
            raise ValueError("missing or unknown manifest fields")
        result = cls(**value)
        if not isinstance(result.installation, str) or not NAME.fullmatch(
            result.installation
        ):
            raise ValueError("invalid installation identity")
        for image in (
            result.application_image,
            result.database_image,
            result.cache_image,
        ):
            if not isinstance(image, str) or not IMAGE.fullmatch(image):
                raise ValueError("immutable local image ID or registry digest required")
        if type(result.database_major) is not int or result.database_major != 17:
            raise ValueError("only PostgreSQL 17 is currently supported")
        for limit in (result.drain_seconds, result.readiness_seconds):
            if type(limit) is not int or not 1 <= limit <= 600:
                raise ValueError("timeouts must be integer seconds in [1, 600]")
        return result

    def container(self, role):
        if role not in {"app", "database", "cache"}:
            raise ValueError("unknown component")
        return f"mesops-{self.installation}-{role}"

    def owns(self, container):
        labels = container.get("Config", {}).get("Labels") or {}
        return labels.get(LABEL) == self.installation
