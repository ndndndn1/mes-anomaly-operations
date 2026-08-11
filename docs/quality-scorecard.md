# Enterprise quality scorecard

The canonical machine-readable record is `quality/scorecard.json`, validated by
`python3 quality/check_score.py`. Category maximums total 100 and the acceptance target is 80.

| Category | Earned | Maximum | Primary evidence |
| --- | ---: | ---: | --- |
| API contract | 15 | 15 | Versioned/legacy paths, RFC 9457, bounded values, nullable score |
| Data integrity | 19 | 20 | PostgreSQL event transaction, equipment lock, batches, after-commit cache |
| Verification | 18 | 20 | Unit, live integration, concurrency, rollback, fallback, mocks, soak harness |
| Operability | 14 | 15 | Request IDs, Prometheus, health probes, resource ceilings, runbook |
| Security | 13 | 15 | Non-root/read-only container, least privilege, localhost bind, threat model |
| Supply chain | 8 | 10 | Lockfile, npm ci/audit, Enforcer, Trivy, SBOM, provenance, Dependabot |
| Documentation | 5 | 5 | Requirements, API, architecture, testing, operations, threat model |
| **Total** | **92** | **100** | **Passes target 80** |

## Hard gates

- Tests: pass (9 JUnit tests and live Compose integration suite).
- Runtime smoke: pass against the localhost-only service.
- Memory: pass (768 MiB application limit with JVM percentage ceiling).
- Security: pass (runtime boundary checks and critical vulnerability gate).
- Documentation examples: pass (API and operating commands are exercised by equivalent tests).

The extended soak is prepared but deliberately requires coordination before consuming shared-host
capacity. It is not represented as completed evidence.
