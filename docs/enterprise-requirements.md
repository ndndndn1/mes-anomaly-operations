# Enterprise requirements

This document is the review index for the hardening contract. Evidence is executable or points to
the smallest relevant implementation boundary.

## Target

A deterministic, retry-safe MES sensor anomaly **evaluation** service for operational decision
support. The target excludes equipment actuation, safety interlocks, industrial protocol clients,
and deployment authentication.

## Inputs

`POST /api/v1/evaluations` and the `/api/judge` compatibility alias accept JSON containing a stable
`eventId`, `lineId`, `equipmentId`, per-sensor finite `low`/`high` limits, and strictly time-ordered
samples. IDs are at most 80 characters. The contract allows 1-64 limits, 1-500 samples, 1-64 sensor
values per sample, and at most 10,000 measurements. Numeric inputs are finite and within +/-1e12;
timestamps are bounded to 30 days past and 5 minutes future.

## Outputs

The JSON response identifies the event/equipment, replay status, evaluated count, and ordered
verdicts. Each verdict contains timestamp, sensor, value, severity, rule, and a finite statistical
`score` or `null` when no statistical score applies. New events return 201, identical replays 200,
and conflicts/invalid requests use RFC 9457 `application/problem+json`. Every response includes
`X-Request-ID`; Prometheus metrics are available at `/actuator/prometheus`.

## Software mocks

The Compose `test` profile supplies deterministic HTTP doubles implemented by
`test/mocks/server.py`: sensor `GET /sample`, read-only PLC `GET /status` with
`controlSupported: false`, and verifier `POST /verify`. These mocks provide repeatable software-only
integration evidence and neither emulate nor connect to physical equipment.

| Requirement | Status | Evidence |
| --- | --- | --- |
| Versioned evaluation API and `/api/judge` compatibility | Met | `JudgeController`, `docs/API.md`, integration suite |
| Strict bounded and finite validation | Met | `ApiModels`, `RequestValidator`, validator tests |
| RFC 9457 problems and no non-finite response scores | Met | `ApiExceptionHandler`, `RobustDetector`, integration suite |
| Immutable idempotent event semantics | Met | `evaluation_event`, canonical hash, concurrent replay/conflict checks |
| PostgreSQL-authoritative transaction and JDBC batches | Met | `EvaluationService`, Flyway V2, rollback/concurrency checks |
| Redis after-commit TTL with correctness fallback | Met | transaction synchronization, cache counter, unreachable-Redis check |
| Deterministic sensor/PLC/verifier test doubles | Met | Compose `test` profile and `test/mocks/server.py` |
| Integration, concurrency, and failure verification | Met | `test/integration.py`; configurable `test/soak.py` prepared |
| Metrics, request IDs, health, and resource limits | Met | Prometheus, `RequestIdFilter`, Compose boundaries, runbook |
| Non-root/read-only container hardening | Met | runtime UID 10001, dropped capabilities, no-new-privileges |
| Locked frontend and clear operator semantics | Met | exact npm versions, lockfile/`npm ci`, result table and replay UI |
| CI and supply-chain gates | Met | unit/integration/smoke, fail-closed dependency/image Trivy, Enforcer, SBOM/provenance |
| Documentation and score at least 80 | Met | API/architecture/runbook/testing/threat model; validated 92/100 |

## Scope boundary

This repository intentionally contains no equipment command path, OPC-UA/Modbus integration, or
authentication implementation. A deployment must provide authenticated ingress, TLS, authorization,
secrets management, and rate limiting. Verdicts are decision support, never safety interlocks.
