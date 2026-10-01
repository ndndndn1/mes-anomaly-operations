"""Compile the protocol specification; reject failed, missing or admitted proofs."""

import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess

THEOREMS = [
    "initial_safe",
    "preserves_safe",
    "reachable_safe",
    "destructive_requires_verified_backup",
    "uncertain_blocks_ingress",
    "no_other_owner_step",
    "no_blind_launch_after_interruption",
]


def verify(lean="lean"):
    source = Path(__file__).with_name("Specification.lean")
    version = subprocess.run(
        [lean, "--version"], text=True, capture_output=True, timeout=10, check=True
    ).stdout.strip()
    result = subprocess.run(
        [lean, str(source)], text=True, capture_output=True, timeout=60
    )
    output = result.stdout + result.stderr
    if result.returncode or "sorryAx" in output or "error:" in output:
        raise RuntimeError("formal verification failed or contains admitted proof")
    if any("'Operations." + name + "'" not in output for name in THEOREMS):
        raise RuntimeError("missing expected theorem evidence")
    printed = re.findall(
        r"'Operations\.([^']+)' depends on axioms: \[([^]]*)\]", output
    )
    if len(printed) != len(THEOREMS) or {name for name, _ in printed} != set(THEOREMS):
        raise RuntimeError("unexpected theorem or axiom output")
    if any(
        set(x.strip() for x in axioms.split(",") if x.strip())
        - {"propext", "Quot.sound", "Classical.choice"}
        for _, axioms in printed
    ):
        raise RuntimeError("unapproved proof axiom")
    return {
        "compiler": version,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "theorems_checked": THEOREMS,
        "passed": len(THEOREMS),
        "total": len(THEOREMS),
        "compiler_output": output.strip(),
        "scope": "abstract upgrade protocol only; external validation evidence is assumed, not proved; no proof of Python, Docker, PostgreSQL or MongoDB internals",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lean", default="lean")
    args = parser.parse_args()
    print(json.dumps(verify(args.lean), indent=2))
