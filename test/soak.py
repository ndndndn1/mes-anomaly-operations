"""Configurable soak harness. Defaults are intentionally short; CI does not run the long mode."""

import json
import os
import time
import urllib.request
import uuid
from datetime import datetime, timezone

API = os.environ.get("API_URL", "http://127.0.0.1:8802")
DURATION_SECONDS = int(os.environ.get("SOAK_DURATION_SECONDS", "60"))
RATE_PER_SECOND = int(os.environ.get("SOAK_RATE_PER_SECOND", "5"))
deadline = time.monotonic() + DURATION_SECONDS
sent = 0
latencies = []

while time.monotonic() < deadline:
    started = time.monotonic()
    now = datetime.now(timezone.utc).isoformat()
    event_id = "soak-" + uuid.uuid4().hex
    payload = {
        "eventId": event_id,
        "lineId": "soak-line",
        "equipmentId": "press-" + str(sent % 8),
        "limits": {"temperature": {"low": 10, "high": 80}},
        "samples": [{"timestamp": now, "values": {"temperature": 45 + (sent % 5) * 0.1}}],
    }
    request = urllib.request.Request(
        API + "/api/v1/evaluations",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 201
    latencies.append(time.monotonic() - started)
    sent += 1
    time.sleep(max(0, 1 / RATE_PER_SECOND - latencies[-1]))

latencies.sort()
p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
print(json.dumps({"sent": sent, "durationSeconds": DURATION_SECONDS, "p95Seconds": round(p95, 4)}))
