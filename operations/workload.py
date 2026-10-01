"""Independent deterministic input and database/response accounting for live upgrades."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import random
import re
import threading
import time


def event(index, seed, base):
    rng = random.Random(seed * 1_000_003 + index)
    limits = {f"sensor-{i}": {"low": 10.0, "high": 80.0} for i in range(4)}
    samples = []
    for sample in range(6):
        values = {
            sensor: round(
                45 + rng.uniform(-2, 2) + (50 if rng.random() < 0.08 else 0), 4
            )
            for sensor in limits
        }
        samples.append(
            {
                "timestamp": (
                    base + timedelta(milliseconds=index, microseconds=sample * 100)
                ).isoformat(),
                "values": values,
            }
        )
    return {
        "eventId": f"work-{seed}-{index}",
        "lineId": "workload",
        "equipmentId": f"equipment-{index % 32}",
        "limits": limits,
        "samples": samples,
    }


def canonical_time(value):
    value = value.replace("Z", "+00:00")
    # PostgreSQL trims trailing fractional zeros; Python 3.10's ISO parser
    # only accepts 3 or 6 fractional digits. Preserve precision by padding.
    value = re.sub(
        r"\.([0-9]{1,6})(?=[+-][0-9]{2}:[0-9]{2}$)",
        lambda match: "." + match.group(1).ljust(6, "0"),
        value,
    )
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def check_response(payload, response):
    if (
        response["eventId"] != payload["eventId"]
        or response["lineId"] != payload["lineId"]
        or response["equipmentId"] != payload["equipmentId"]
    ):
        raise AssertionError("response identity mismatch")
    expected = {
        (canonical_time(s["timestamp"]), k): v
        for s in payload["samples"]
        for k, v in s["values"].items()
    }
    if response["evaluated"] != len(expected) or len(response["verdicts"]) != len(
        expected
    ):
        raise AssertionError("wrong evaluation count")
    seen = set()
    for verdict in response["verdicts"]:
        key = (canonical_time(verdict["timestamp"]), verdict["sensor"])
        if key in seen or key not in expected or verdict["value"] != expected[key]:
            raise AssertionError("missing/duplicate/changed measurement")
        seen.add(key)
        limit = payload["limits"][verdict["sensor"]]
        if not limit["low"] <= verdict["value"] <= limit["high"]:
            if verdict["severity"] != "critical" or verdict["rule"] != "absolute_limit":
                raise AssertionError("absolute-limit semantics changed")


def exercise(controller, candidate, total=10000, seed=1, workers=4):
    if total < 100 or total > 100000:
        raise ValueError("bounded workload requires 100..100000 events")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    base = datetime.now(timezone.utc)
    times = []
    queued = 0
    accepted = 0
    warmup = min(1000, total // 5)
    mutex = threading.Lock()
    first = threading.Event()
    stop = threading.Event()

    def submit(index):
        nonlocal queued, accepted
        if stop.is_set():
            return
        payload = event(index, seed, base)
        started = time.monotonic()
        result = controller.evaluate(payload)
        with mutex:
            times.append(time.monotonic() - started)
            if result.get("queued"):
                queued += 1
            else:
                accepted += 1
                if accepted >= warmup:
                    first.set()
        if not result.get("queued"):
            check_response(payload, result)

    error = []

    def guarded_submit(index):
        try:
            return submit(index)
        except BaseException:
            stop.set()
            first.set()
            raise

    def produce():
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(guarded_submit, range(total)))
        except BaseException as exc:
            error.append(exc)
            stop.set()
            first.set()

    started = time.monotonic()
    producer = threading.Thread(target=produce)
    producer.start()
    try:
        if not first.wait(300):
            raise RuntimeError("producer failed to start")
        if stop.is_set():
            producer.join()
        if error:
            raise error[0]
        maintenance_start = time.monotonic()
        deadline = maintenance_start + 60
        while True:
            try:
                upgrade = controller.upgrade(candidate)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise RuntimeError("maintenance lock acquisition deadline exceeded")
                time.sleep(0.05)
        producer.join(timeout=600)
        if producer.is_alive():
            raise RuntimeError("producer deadline exceeded")
    finally:
        # Never let the acceptance harness destroy a stack with active writers.
        # In-flight controller calls have bounded network/subprocess deadlines;
        # queued executor work checks stop before touching the installation.
        stop.set()
        producer.join()
    if error:
        raise error[0]
    maintenance_seconds = time.monotonic() - maintenance_start
    pending = list(
        controller.storage.db.mesops_input_queue.find(
            {"installation": controller.name, "state": "pending"}
        )
    )

    def retry(item):
        result = controller.evaluate(item["payload"])
        if result.get("queued"):
            raise RuntimeError("input still gated after completed operation")
        check_response(item["payload"], result)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(retry, pending))
    # The independent DB read checks payload, durable result and per-event row cardinality.
    raw = controller.stack.sql(
        """WITH samples AS (
          SELECT event_id, json_agg(json_build_object(
            'timestamp',observed_at,'sensor',sensor,'value',value,
            'lineId',line_id,'equipmentId',equipment_id)) AS samples
          FROM sensor_sample GROUP BY event_id
        ), verdicts AS (
          SELECT event_id, json_agg(json_build_object(
            'timestamp',observed_at,'sensor',sensor,'value',value,
            'severity',severity,'rule',rule_name,'score',score,
            'lineId',line_id,'equipmentId',equipment_id)) AS verdicts
          FROM sensor_verdict GROUP BY event_id
        )
        SELECT row_to_json(t)::text FROM (
          SELECT e.event_id,e.response_body,s.samples,v.verdicts
          FROM evaluation_event e
          LEFT JOIN samples s ON s.event_id=e.event_id
          LEFT JOIN verdicts v ON v.event_id=e.event_id
          WHERE e.line_id='workload' ORDER BY e.event_id
        ) t;""",
        timeout=120,
    )
    actual = {}
    for line in raw.splitlines():
        row = json.loads(line)
        if row["event_id"] in actual:
            raise AssertionError("duplicate authoritative event")
        actual[row["event_id"]] = row
    if len(actual) != total:
        raise AssertionError("missing/extra authoritative events")
    response_hash = hashlib.sha256()
    for index in range(total):
        payload = event(index, seed, base)
        row = actual[payload["eventId"]]
        if len(row["samples"] or []) != 24 or len(row["verdicts"] or []) != 24:
            raise AssertionError("missing/duplicate child records")
        expected_values = {
            (canonical_time(x["timestamp"]), k): v
            for x in payload["samples"]
            for k, v in x["values"].items()
        }
        actual_values = {
            (canonical_time(x["timestamp"]), x["sensor"]): x["value"]
            for x in row["samples"]
        }
        if actual_values != expected_values:
            raise AssertionError("stored sample values changed")
        if any(
            x["lineId"] != payload["lineId"]
            or x["equipmentId"] != payload["equipmentId"]
            for x in row["samples"] + row["verdicts"]
        ):
            raise AssertionError("stored child record ownership changed")
        check_response(
            payload,
            {
                "eventId": payload["eventId"],
                "lineId": payload["lineId"],
                "equipmentId": payload["equipmentId"],
                "evaluated": 24,
                "verdicts": row["verdicts"],
            },
        )
        response = json.loads(row["response_body"])
        check_response(payload, response)
        response_hash.update(json.dumps(response, sort_keys=True).encode())
    acknowledged = controller.storage.db.mesops_input_queue.count_documents(
        {"installation": controller.name, "state": "acknowledged"}
    )
    remaining = controller.storage.db.mesops_input_queue.count_documents(
        {"installation": controller.name, "state": "pending"}
    )
    if acknowledged != total or remaining:
        raise AssertionError("queue and database disagree")
    timings = list(
        controller.storage.db.mesops_input_queue.find(
            {"installation": controller.name, "state": "acknowledged"},
            {"created_at": 1, "acknowledged_at": 1},
        )
    )
    latency = sorted(
        (x["acknowledged_at"] - x["created_at"]).total_seconds() for x in timings
    )
    operation = controller.journal.read(controller.name)["operation"]
    gate_seconds = (operation["completed_at"] - operation["started_at"]).total_seconds()
    elapsed = time.monotonic() - started
    return {
        "events": total,
        "measurements": total * 24,
        "seed": seed,
        "workers": workers,
        "queued_during_maintenance": queued,
        "acknowledged": acknowledged,
        "pending": remaining,
        "lost_acknowledged_events": 0,
        "duplicate_events": 0,
        "response_hash": response_hash.hexdigest(),
        "seconds": round(elapsed, 3),
        "effective_events_per_second": round(total / elapsed, 3),
        "write_gate_closed_seconds": gate_seconds,
        "acknowledgement_p95_seconds": latency[int(0.95 * (len(latency) - 1))],
        "maintenance_and_producer_seconds": round(maintenance_seconds, 3),
        "input_attempt_p95_seconds": sorted(times)[int(0.95 * (len(times) - 1))],
        "upgrade_outcome": upgrade["outcome"],
        "scope": "synthetic reference-stack correctness; not a customer throughput SLA",
    }
