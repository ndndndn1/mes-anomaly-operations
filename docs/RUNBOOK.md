# Operations runbook

## Readiness and observation

- Readiness/liveness: `GET /actuator/health/readiness` and `/actuator/health/liveness`
- Metrics: `GET /actuator/prometheus`
- Correlation: preserve or generate `X-Request-ID` at ingress and search application logs by it.
- Important counters: `mes_evaluations_total{outcome=...}` and
  `mes_redis_after_commit_failures_total`.

## Failure handling

PostgreSQL unavailable means evaluation is unavailable; callers may retry the **same** event ID.
Redis unavailable does not make committed evaluation unavailable. Alert on sustained Redis failure
counter growth, repair Redis, and allow new events to repopulate the cache; no database replay is
required.

An idempotency conflict means a producer reused an event ID with different data. Do not generate a
new ID automatically until the producer has reconciled which physical event the payload describes.

## Capacity and retention

Compose defaults the app to 1 CPU, 768 MiB, and 256 PIDs. Validate these limits with a coordinated
soak before changing traffic. Redis is capped at 64 MiB and each history key is length- and
TTL-bounded. Database retention is site policy; archive by event while preserving referential
integrity. Back up PostgreSQL before schema upgrades.

## Shutdown

The application uses graceful shutdown. Stop on-demand services after verification with
`docker compose down`; add `-v` only when deliberately discarding local test database state.
