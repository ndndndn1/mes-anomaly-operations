"""Build offline test releases from an already cached immutable application image."""

import argparse
import io
import json
import subprocess
import tarfile
from .control.manifest import IMAGE

MIGRATION = """SET LOCAL lock_timeout = '500ms';
CREATE INDEX evaluation_event_line_completed ON evaluation_event(line_id, completed_at);
CREATE TABLE mesops_release (version integer PRIMARY KEY, description text NOT NULL);
INSERT INTO mesops_release VALUES (3, 'line-level operation lookup');
"""


def build(base, kind):
    if not IMAGE.fullmatch(base):
        raise ValueError("immutable base required")
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", base]))[0]
    # Local images may expose RepoDigests that look remote but were never
    # pushed. Always resolve an ID-bound local alias instead of contacting it.
    base_ref = "mesops-fixture-base:" + image["Id"].split(":", 1)[1]
    existing = subprocess.run(
        ["docker", "image", "inspect", base_ref], capture_output=True, timeout=20
    )
    if existing.returncode == 0 and json.loads(existing.stdout)[0]["Id"] != image["Id"]:
        raise RuntimeError("fixture base alias identity mismatch")
    subprocess.run(
        ["docker", "tag", image["Id"], base_ref],
        check=True,
        capture_output=True,
        timeout=20,
    )
    dockerfile = "FROM " + base_ref + "\n"
    assets = {}
    if kind == "startup-failure":
        dockerfile += "ENV DETECTOR_WINDOW_SIZE=1\n"
    elif kind in ["schema-upgrade", "invalid-sql", "semantic-failure"]:
        dockerfile += "ENV SPRING_FLYWAY_LOCATIONS=classpath:db/migration,filesystem:/app/operations-migrations\nCOPY V3__line_operation_lookup.sql /app/operations-migrations/V3__line_operation_lookup.sql\n"
        assets["V3__line_operation_lookup.sql"] = (
            MIGRATION
            + (
                "SELECT nonexistent_column FROM evaluation_event;\n"
                if kind == "invalid-sql"
                else ""
            )
        ).encode()
        if kind == "semantic-failure":
            assets["V3__line_operation_lookup.sql"] += b"""
CREATE FUNCTION corrupt_stored_response() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.response_body IS NOT NULL THEN
    NEW.response_body := replace(NEW.response_body, 'critical', 'normal');
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER corrupt_response BEFORE UPDATE ON evaluation_event
FOR EACH ROW EXECUTE FUNCTION corrupt_stored_response();
"""
    else:
        raise ValueError("unknown fixture")
    assets["Dockerfile"] = dockerfile.encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in assets.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    result = subprocess.run(
        ["docker", "build", "--network=none", "--pull=false", "-q", "-"],
        input=stream.getvalue(),
        capture_output=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError("offline fixture build failed")
    identifier = result.stdout.decode().strip().splitlines()[-1]
    if not IMAGE.fullmatch(identifier):
        raise RuntimeError("build did not return immutable image ID")
    return {
        "kind": kind,
        "base_image": image["Id"],
        "image": identifier,
        "scope": "test fixture, not vendor software",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument(
        "--kind",
        choices=[
            "startup-failure",
            "schema-upgrade",
            "invalid-sql",
            "semantic-failure",
        ],
        required=True,
    )
    args = parser.parse_args()
    print(json.dumps(build(args.base_image, args.kind)))
