# API contract and examples

## Create an evaluation

```bash
python3 - <<'PYTHON' > event.json
from datetime import datetime, timezone
import json
import uuid
print(json.dumps({
    "eventId": "operator-" + uuid.uuid4().hex,
    "lineId": "line-a",
    "equipmentId": "press-7",
    "limits": {"temperature": {"low": 10, "high": 80}},
    "samples": [{"timestamp": datetime.now(timezone.utc).isoformat(),
                 "values": {"temperature": 92}}]
}))
PYTHON
curl --fail-with-body http://127.0.0.1:8802/api/v1/evaluations \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: operator-example-1' \
  --data-binary @event.json
```

Generate the synthetic payload once, then keep the same file for a retry. Running
the generator again creates a new event. The timestamp is generated at execution
time so this example does not expire as a hard-coded historical date would.
For an `operations.control` installation, deliver the same file with
`python3 -m operations.control evaluate --manifest deployment.json < event.json`;
that isolated stack does not expose the Compose example's HTTP port.

A new event returns `201`; an identical replay returns `200`. The response contains an ordered
verdict per measurement. `score` is nullable: it is `null` for an absolute-limit verdict and a
finite number for statistical rules.

## Compatibility path

`POST /api/judge` accepts the exact same payload. It preserves existing HTTP clients while making
the versioned resource path the documented default.

## Validation and problems

- IDs: 1-80 characters, starting alphanumeric, then alphanumeric plus `._:-`.
- 1-64 limits, 1-500 samples, 1-64 values per sample, at most 10,000 measurements.
- Timestamps must strictly increase and fall within 30 days past / 5 minutes future.
- Every value needs a matching limit. Values and limit endpoints must be finite, within +/-1e12,
  and use `low < high`.
- Unknown JSON properties and malformed shapes return `400`; invariant violations return `422`.

Errors use `application/problem+json` with RFC 9457 members plus `requestId` and, where useful, an
`errors` object. Invalid supplied request IDs are replaced with a generated UUID.
