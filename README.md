# MES Anomaly Operations

An enterprise-oriented Spring Boot, PostgreSQL, Redis, and React/TypeScript reference slice for
repeatable sensor anomaly evaluation in manufacturing operations. It is decision-support software:
it does **not** control equipment, speak OPC-UA/Modbus, or provide production authentication.

## Contract and guarantees

- `POST /api/v1/evaluations` is the canonical API; `POST /api/judge` is a compatibility alias with
  the same request and response.
- A caller-supplied `eventId` is an idempotency key. Repeating an identical payload returns the
  stored verdict (`200`, `replayed: true`); reusing it for different content returns RFC 9457
  `409 application/problem+json`.
- IDs, timestamps, sensor counts, measurement counts, numeric values, and limits are strictly
  bounded. Non-finite numbers are rejected. Absolute-limit verdicts use `score: null` because a
  robust z-score does not apply; the API never emits invalid JSON `Infinity`.
- PostgreSQL is authoritative. Equipment-scoped advisory locking, event claim, baseline reads, and
  JDBC batch writes share one transaction. Redis is a bounded, 24-hour, after-commit acceleration
  cache; Redis failure cannot reverse or fail a committed evaluation.
- Every response carries `X-Request-ID`; Prometheus metrics are exposed at `/actuator/prometheus`.

See [enterprise requirements](docs/enterprise-requirements.md),
[quality scorecard](docs/quality-scorecard.md), [API examples](docs/API.md),
[architecture](docs/ARCHITECTURE.md),
[operations runbook](docs/RUNBOOK.md), [testing](docs/TESTING.md), and
[threat model](docs/THREAT_MODEL.md).

## Run and verify

The only host-bound port is `127.0.0.1:8802`.

```bash
docker compose up -d --build --wait
python3 smoke.py
docker compose --profile test run --rm test
docker compose --profile test run --rm integration-test
python3 quality/check_score.py
docker compose down
```

The test profile provides deterministic HTTP sensor, PLC-status, and result-verifier doubles. The
PLC double is explicitly read-only (`controlSupported: false`). Integration checks cover the
versioned and compatibility paths, concurrent idempotency, conflict detection, transaction
rollback, unreachable-Redis fallback, RFC 9457 errors, request IDs, metrics, and mocks.

For a configurable soak after the stack is healthy:

```bash
SOAK_DURATION_SECONDS=3600 SOAK_RATE_PER_SECOND=20 python3 test/soak.py
```

The long soak is intentionally not part of pull-request CI. Coordinate its duration and machine
load before running it on a shared host.

## Deployment notes

The Compose file sets CPU, memory, PID, read-only filesystem, dropped-capability, and
`no-new-privileges` boundaries for the application. The runtime image uses UID/GID `10001`, and the
frontend uses a committed lockfile with `npm ci`. Replace local database credentials with a secrets
provider in any real deployment and terminate TLS at an authenticated ingress.

## Explicit non-goals

- Equipment actuation or safety interlocks
- OPC-UA, Modbus, or vendor PLC protocol integration
- Authentication, authorization, tenancy, or Internet exposure
- A substitute for calibrated site thresholds, alarm management, or a safety-rated system
