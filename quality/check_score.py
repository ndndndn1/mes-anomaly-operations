#!/usr/bin/env python3
"""Validate the machine-readable enterprise quality scorecard using only stdlib."""

import json
from pathlib import Path

path = Path(__file__).with_name("scorecard.json")
data = json.loads(path.read_text(encoding="utf-8"))
assert data["schema_version"] == "1.0"
assert isinstance(data["target"], int) and 0 <= data["target"] <= 100
categories = data["categories"]
assert isinstance(categories, list) and categories
assert len({category["id"] for category in categories}) == len(categories)
assert sum(category["max"] for category in categories) == 100
for category in categories:
    assert isinstance(category["id"], str) and category["id"]
    assert isinstance(category["max"], int) and category["max"] > 0
    assert isinstance(category["earned"], int) and 0 <= category["earned"] <= category["max"]
    assert isinstance(category["evidence"], list) and category["evidence"]
    assert all(isinstance(item, str) and item.strip() for item in category["evidence"])
score = sum(category["earned"] for category in categories)
assert data["score"] == score
assert score >= data["target"]
required_gates = {"tests", "runtime_smoke", "memory", "security", "docs_examples"}
assert set(data["hard_gates"]) == required_gates
assert all(data["hard_gates"][gate] is True for gate in required_gates)
print(f"quality scorecard passed: {score}/100 (target {data['target']})")
