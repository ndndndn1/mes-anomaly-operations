#!/usr/bin/env python3
"""Fast repository-level supply-chain invariants used before expensive builds."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = json.loads((root / "web/package.json").read_text())
lock = json.loads((root / "web/package-lock.json").read_text())
assert lock["lockfileVersion"] == 3
assert lock["packages"][""]["dependencies"] == package["dependencies"]
assert all(version != "latest" and not version.startswith(("^", "~")) for version in package["dependencies"].values())
dockerfile = (root / "Dockerfile").read_text()
assert "npm ci --ignore-scripts" in dockerfile
assert "USER 10001:10001" in dockerfile
compose = (root / "compose.yaml").read_text()
for control in ("read_only: true", "cap_drop: [ALL]", "no-new-privileges:true", "pids_limit:"):
    assert control in compose, control
print("supply-chain and runtime hardening invariants passed")
