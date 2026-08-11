import json
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)
samples = [
    {"timestamp": (now + timedelta(seconds=i)).isoformat(), "values": {"temperature": 45.0 + (i % 3) * 0.1}}
    for i in range(6)
]
samples.append({"timestamp": (now + timedelta(seconds=7)).isoformat(), "values": {"temperature": 92.0}})
payload = {"eventId": "smoke-" + uuid.uuid4().hex, "lineId": "smoke", "equipmentId": "press-1", "limits": {"temperature": {"low": 10, "high": 80}}, "samples": samples}
request = urllib.request.Request("http://127.0.0.1:8802/api/v1/evaluations", data=json.dumps(payload).encode(), headers={"content-type": "application/json", "X-Request-ID": "smoke-request"})
with urllib.request.urlopen(request, timeout=10) as response:
    result = json.load(response)
    assert response.status == 201
    assert response.headers["X-Request-ID"] == "smoke-request"
assert result["evaluated"] == 7, result
assert result["verdicts"][-1]["rule"] == "absolute_limit", result
assert result["verdicts"][-1]["score"] is None, result
print("MES smoke passed")
