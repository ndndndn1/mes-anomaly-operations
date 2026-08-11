# Architecture and data consistency

The HTTP adapter validates the bounded contract and sends it to one transactional application
service. The service hashes the canonical request, claims `evaluation_event.event_id`, obtains a
PostgreSQL transaction-level advisory lock for the line/equipment pair, reads recent authoritative
samples, evaluates the ordered batch, and batch-inserts samples and verdicts. It stores the exact
response before commit.

Concurrent identical event IDs converge on one database row: one request creates it and contenders
read the committed response. Different request content for an existing event ID is a conflict.
Equipment locking also prevents two different events from selecting the same stale baseline.

Only after commit does the service push bounded per-sensor history to Redis and refresh its TTL.
Scoring never depends on Redis, so eviction, restart, or unavailability changes latency telemetry,
not verdict correctness. `mes_redis_after_commit_failures_total` makes cache degradation visible.

The `sensor_sample` stream is the authoritative detector baseline. `sensor_verdict` is the durable
decision record, and `evaluation_event` is the idempotency/audit envelope. Flyway owns all schema
changes.
