"""Black-box contract, concurrency, rollback, Redis fallback, and mock integration checks."""

import concurrent.futures
import copy
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

API = os.environ.get("API_URL", "http://127.0.0.1:8802")
FALLBACK = os.environ.get("FALLBACK_API_URL", API)
SENSOR = os.environ.get("SENSOR_MOCK_URL")
PLC = os.environ.get("PLC_MOCK_URL")
VERIFIER = os.environ.get("VERIFIER_MOCK_URL")


def fetch(url, path, payload=None, headers=None):
    data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = urllib.request.Request(
        url + path,
        data=data,
        headers={"content-type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type()
            body = response.read()
            return response.status, content_type, response.headers, json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get_content_type(), error.headers, json.load(error)


def payload(event_id, equipment="press-integration"):
    now = datetime.now(timezone.utc)
    samples = [
        {"timestamp": (now + timedelta(milliseconds=index)).isoformat(), "values": {"temperature": 45 + (index % 3) * 0.1}}
        for index in range(6)
    ]
    samples.append({"timestamp": (now + timedelta(milliseconds=7)).isoformat(), "values": {"temperature": 92.0}})
    return {
        "eventId": event_id,
        "lineId": "integration-line",
        "equipmentId": equipment,
        "limits": {"temperature": {"low": 10.0, "high": 80.0}},
        "samples": samples,
    }


def assert_problem(result, status):
    actual_status, content_type, headers, body = result
    assert actual_status == status, result
    assert content_type == "application/problem+json", result
    assert body["status"] == status and body["title"] and body["detail"], body
    assert body["requestId"] == headers["X-Request-ID"], (body, headers)


if SENSOR and PLC and VERIFIER:
    assert fetch(SENSOR, "/sample")[3]["values"] == {"temperature": 45.0}
    plc = fetch(PLC, "/status")[3]
    assert plc == {"controlSupported": False, "state": "simulated_idle"}, plc

event = "integration-" + uuid.uuid4().hex
request = payload(event)
status, _, headers, created = fetch(API, "/api/v1/evaluations", request, {"X-Request-ID": "integration-request"})
assert status == 201 and headers["X-Request-ID"] == "integration-request", (status, headers, created)
assert created["evaluated"] == 7 and created["replayed"] is False, created
assert created["verdicts"][-1]["rule"] == "absolute_limit", created
assert created["verdicts"][-1]["score"] is None, created
assert fetch(VERIFIER, "/verify", created)[3] == {"valid": True, "verifier": "deterministic-v1"}

status, _, _, replay = fetch(API, "/api/judge", request)
assert status == 200 and replay["replayed"] is True and replay["verdicts"] == created["verdicts"], replay

conflict = copy.deepcopy(request)
conflict["samples"][0]["values"]["temperature"] = 46.0
assert_problem(fetch(API, "/api/v1/evaluations", conflict), 409)

unknown = copy.deepcopy(payload("unknown-" + uuid.uuid4().hex))
unknown["unexpected"] = True
assert_problem(fetch(API, "/api/v1/evaluations", unknown), 400)

reversed_request = payload("reversed-" + uuid.uuid4().hex)
reversed_request["samples"][1]["timestamp"] = reversed_request["samples"][0]["timestamp"]
assert_problem(fetch(API, "/api/v1/evaluations", reversed_request), 422)

# All contenders submit one immutable event. Exactly one transaction creates it; all others replay.
concurrent_request = payload("concurrent-" + uuid.uuid4().hex, "press-concurrent")
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(lambda _: fetch(API, "/api/v1/evaluations", concurrent_request), range(8)))
statuses = sorted(result[0] for result in results)
assert statuses == [200] * 7 + [201], statuses
assert len({json.dumps(result[3]["verdicts"], sort_keys=True) for result in results}) == 1

# Test-only failure occurs after both JDBC batches but before commit. The same event ID must then
# succeed, demonstrating full rollback. This app also has an unreachable Redis endpoint, proving
# cache failure cannot corrupt or fail a committed PostgreSQL evaluation.
rollback_request = payload("rollback-" + uuid.uuid4().hex, "press-rollback")
assert_problem(fetch(
    FALLBACK,
    "/api/v1/evaluations",
    rollback_request,
    {"X-Test-Fail-Before-Commit": "true"},
), 500)
status, _, _, fallback_created = fetch(FALLBACK, "/api/v1/evaluations", rollback_request)
assert status == 201 and fallback_created["replayed"] is False, fallback_created
status, _, _, fallback_replay = fetch(FALLBACK, "/api/v1/evaluations", rollback_request)
assert status == 200 and fallback_replay["replayed"] is True, fallback_replay

with urllib.request.urlopen(API + "/actuator/prometheus", timeout=10) as response:
    metrics = response.read().decode()
assert "mes_evaluations_total" in metrics, metrics[-1000:]

print("MES integration, concurrency, rollback, Redis fallback, and mock checks passed")
