"""Real API concurrency, conflicting identity and lost-response reconciliation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from .control.journal import Conflict, host_lock


def exercise(controller):
    payload = {
        "eventId": "queue-concurrent",
        "lineId": "queue-check",
        "equipmentId": "synthetic",
        "limits": {"temperature": {"low": 10, "high": 80}},
        "samples": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "values": {"temperature": 95},
            }
        ],
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: controller.evaluate(payload), range(8)))
    if any(x.get("eventId") != payload["eventId"] or x.get("queued") for x in results):
        raise AssertionError("concurrent controller acknowledgement failed")
    queue = controller.storage.db.mesops_input_queue
    query = {"installation": controller.name, "event_id": payload["eventId"]}
    first = queue.find_one(query)
    controller.evaluate(payload)
    if first["acknowledged_at"] != queue.find_one(query)["acknowledged_at"]:
        raise AssertionError("replay changed first acknowledgement time")
    conflicting = {**payload, "equipmentId": "different"}
    try:
        controller.evaluate(conflicting)
    except Conflict:
        pass
    else:
        raise AssertionError("conflicting event identity accepted")
    uncertain = {**payload, "eventId": "queue-lost-response"}
    original = controller.stack.api

    def lose_response(path, body=None):
        original(path, body)
        raise RuntimeError("injected response loss after real commit")

    controller.stack.api = lose_response
    try:
        try:
            controller.evaluate(uncertain)
        except RuntimeError:
            pass
        else:
            raise AssertionError("response loss not injected")
    finally:
        controller.stack.api = original
    record = queue.find_one(
        {"installation": controller.name, "event_id": uncertain["eventId"]}
    )
    if record["state"] != "pending":
        raise AssertionError("uncertain request reported acknowledged")
    response = controller.evaluate(uncertain)
    if not response.get("replayed"):
        raise AssertionError("lost response was not reconciled through idempotency")
    counts = []
    for table in ["evaluation_event", "sensor_sample", "sensor_verdict"]:
        counts.append(
            int(
                controller.stack.sql(
                    f"SELECT count(*) FROM {table} WHERE line_id='queue-check';"
                )
            )
        )
    if counts != [2, 2, 2]:
        raise AssertionError("retry duplicated or lost authoritative records")
    if (
        queue.count_documents(
            {"installation": controller.name, "state": "acknowledged"}
        )
        != 2
    ):
        raise AssertionError("queue acknowledgement count mismatch")
    invalid = {**payload, "eventId": "queue-invalid", "unexpected": True}
    valid = {**payload, "eventId": "queue-after-invalid"}
    with host_lock(controller.name):
        if not controller.evaluate(invalid).get("queued") or not controller.evaluate(
            valid
        ).get("queued"):
            raise AssertionError("maintenance did not queue both inputs")
    replay = controller.replay()
    if replay != {"acknowledged": 1, "rejected": 1, "pending": 0}:
        raise AssertionError("invalid input blocked valid queued input")
    rejected = controller.evaluate(invalid)
    if not rejected.get("rejected") or rejected.get("http_status") != 400:
        raise AssertionError("definitive rejection not retained")
    if int(
        controller.stack.sql(
            "SELECT count(*) FROM evaluation_event WHERE event_id='queue-invalid';"
        )
    ):
        raise AssertionError("invalid payload persisted in application")
    counts = [
        int(
            controller.stack.sql(
                f"SELECT count(*) FROM {table} WHERE line_id='queue-check';"
            )
        )
        for table in ["evaluation_event", "sensor_sample", "sensor_verdict"]
    ]
    if counts != [3, 3, 3]:
        raise AssertionError("post-rejection input not durably evaluated")
    return {
        "invalid_input_rejected_without_blocking": True,
        "parallel_requests": 8,
        "distinct_events": 3,
        "authoritative_counts": counts,
        "conflict_refused": True,
        "lost_response_reconciled": True,
        "first_acknowledgement_preserved": True,
    }
