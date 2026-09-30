# Manufacturing Software Database Upgrade Rehearsal

This module supports a concrete operations problem: detecting partial schema/data changes before a manufacturing application upgrade reaches a customer environment. It extends MES Anomaly Operations with an isolated PostgreSQL fault-recovery rehearsal. It does not deploy KLA software or control equipment.

## Role and purpose

The public KLA [Division MACH Software Applications Engineer posting](https://kla.wd1.myworkdayjobs.com/Search/job/Hwaseong-si-Korea/Division-MACH-Software-Applications-Engineer_2635584-1), checked 2026-09-30, emphasizes installation, upgrades, Linux/database troubleshooting, operational reliability and documentation. This project addresses those technical themes. It does not imply KLA endorsement or prove prior Klarity experience, customer work, language proficiency or all hiring qualifications.

## Run

Requirements: Linux, Python 3.10+, Docker, and a locally available `postgres:17-alpine` image. The runner resolves the image to its local immutable digest. It makes no image downloads. No new Python dependencies.

```sh
python3 -m operations.rehearse
python3 -m unittest discover -s operations/tests -v
```

Every run creates a unique disposable PostgreSQL container with `--network none`, no published ports, no host data mounts, non-root UID, memory/CPU/PID limits and tmpfs storage. Local trust authentication exists only inside this network-isolated synthetic fixture. Never reuse it in production. The runner removes its container on ordinary success/failure. A machine crash or SIGKILL may leave a container; identify its `mes-rehearsal-` prefix and verify ownership before removal.

## Quality comparison

The fixed scenarios are normal migration, invalid SQL, lock timeout, duplicate primary key, and connection termination before commit. Both modes receive the same statements and synthetic data. The baseline uses autocommit; the improved mode wraps transactional DDL and data changes in one transaction, stops on SQL errors and bounds lock waits.

Success requires the expected schema and data. Each injected failure must preserve both the original data hash and original schema. Exit status is nonzero when the improved mode fails a scenario. The runner records every scenario; unexpected harness errors abort the run and are not counted as a pass.

Measured in the isolated fixture: baseline 2/5, transactional mode 5/5. These are deterministic fault checks, not an estimate of production failure probability or recovery SLA. Measurements are in `results.json`. No claim of novel transaction semantics or superiority over standard migration tools is made. The value is an executable customer-support rehearsal and precise failure evidence.

Initial harness failures exposed tmpfs ownership and temporary initdb readiness races. The final harness assigns tmpfs to the image's PostgreSQL UID and waits for PID 1 to become PostgreSQL, rather than treating the initialization server as ready.

## Requirement coverage

| Requirement | Verification | Status |
|---|---|---|
| Successful upgrade has expected schema and data | real PostgreSQL normal scenario | passed |
| SQL error leaves no partial migration | real PostgreSQL invalid SQL | passed |
| Lock wait is bounded and original data remains | real PostgreSQL held lock + timeout | passed |
| Constraint failure rolls back changes | real PostgreSQL duplicate key | passed |
| Connection interruption does not commit partial changes | terminate fixture session | passed |
| Process invocation is bounded and SQL stays on stdin | 2 unit tests | passed |
| Klarity KD/ACE upgrade | licensed product unavailable | not executed |
| Oracle / PL-SQL compatibility | Oracle unavailable | not executed |
| Customer production rollout | no customer environment | not executed |

Implementation requirements: 6/9 verified, 0 known failures, 3 not executed. This denominator includes the unexecuted requirements. Formal model: 3/3 Lean theorems, separately counted. `Specification.lean` models the intended outcome transition only; it does not prove PostgreSQL internals, Python implementation, filesystem durability or production safety.

## Support runbook

1. Capture the release version and database engine/version without credentials or production payloads.
2. Reproduce with synthetic data in the isolated harness. Keep error category, statement stage and data/schema verification together.
3. Classify invalid SQL as migration incompatibility, duplicate key as a data/constraint conflict, lock timeout as contention, and interrupted connection as an uncertain client outcome. In a real system reconcile committed version before retrying.
4. Use additive/backward-compatible migrations and verified backup/restore for changes that cannot be transactionally rolled back. The included fixture is transactional DDL only.
5. Escalate with exact reproduction steps and expected/observed behavior. Do not silently retry a failed production upgrade.

## Not implemented

Production deployment controller, application binary rollback, PostgreSQL backup restoration, Oracle compatibility, distributed transactions, destructive/nontransactional migrations, durable crash recovery, and Klarity integration. The existing Spring application has not been revalidated by this database-only addition. Its separate integration tests remain the appropriate application-level gate.

## Primary references

- [PostgreSQL 17 transaction tutorial](https://www.postgresql.org/docs/17/tutorial-transactions.html): transaction blocks, rollback and per-statement autocommit semantics.
- [PostgreSQL 17 client connection defaults](https://www.postgresql.org/docs/17/runtime-config-client.html): `lock_timeout` bounds time waiting for locks. It is not a complete migration-duration bound; the harness also bounds the client subprocess.

These references explain the database behavior being exercised. The synthetic fixture is not a published dataset or a reproduction of a KLA system.
