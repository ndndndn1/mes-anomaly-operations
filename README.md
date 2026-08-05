# MES Anomaly Operations

A Spring Boot, PostgreSQL, Redis, and React/TypeScript vertical slice for repeatable sensor anomaly
judgment in manufacturing execution workflows.

## What it implements

- Ordered batch validation for line and equipment sensor samples.
- Absolute safety limits and robust z-score detection based on Redis history.
- PostgreSQL persistence with a Flyway-managed schema and lookup index.
- A React/TypeScript page that exercises the same API served by Spring Boot.
- Health checks and dependency readiness in Docker Compose.

## Run and verify

```bash
docker compose up -d --build --wait
python3 smoke.py
docker compose down
```

The service is available only on `127.0.0.1:8802`. The smoke scenario sends six baseline samples
and one out-of-range temperature, then verifies the persisted evaluation response.

Run unit tests independently with:

```bash
docker compose run --rm test
```

## Design notes

Redis contains a bounded per-sensor history for low-latency scoring; PostgreSQL remains the durable
record. An explicit `/api/seed` endpoint supports controlled cold-start seeding. The detector uses
deterministic statistics and does not substitute fixed mock output for a model or rule engine.

## Limits

- Authentication and tenant isolation are deployment concerns outside this reference slice.
- Site-specific alarm codes and calibrated thresholds must be supplied before production use.
- Long-term analytics should consume the persisted verdict stream rather than Redis history.
