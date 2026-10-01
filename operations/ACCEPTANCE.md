# Manufacturing application installation and recovery acceptance contract

Status: reference-stack acceptance passed (22/22); vendor boundaries remain below. The previous 2-row PostgreSQL rehearsal is a component test, not an operational tool or a completion gate.

Target user: an applications/support engineer installing, upgrading and diagnosing a Linux manufacturing application. The actual KLA role emphasizes installation, upgrades, database/Linux troubleshooting, operational reliability and escalation to engineering. The reference workload is this repository's real MES Spring API, PostgreSQL authoritative records and Redis acceleration layer.

## Required executable workflow

1. Validate an explicit installation manifest and locally available immutable application/database/cache images. Reject incompatible database versions, missing resources, ambiguous targets and unmanaged containers before mutation. Never infer permission from a container name.
2. Install an isolated reference application stack with bounded resources and no public listeners. Check actual API and database readiness. Persist installation identity, image IDs, operations and outcomes in MongoDB; store private evidence and backups in GridFS in this host environment.
3. Diagnose an existing managed installation: application readiness, database reachability, database migration versions, cache degradation, image identity, resource exhaustion and lock contention. Produce actionable, sanitized evidence without passwords or customer payloads.
4. Before upgrade, quiesce application writes with a bounded drain and verify the drain. Capture a consistent database backup and complete authoritative data/schema fingerprints. Restore that backup into an isolated database and verify it before allowing upgrade. A dump process exit code alone is not backup verification.
5. Apply a versioned application release and schema migration with bounded deadlines and durable step records. Reject concurrent operations for the same installation. Resume after operator interruption by reconciling actual containers, migrations and journal state, not blindly repeating mutations.
6. Validate the new application with its real API and existing records before admitting writes. On failure, restore the previous application image and, where required, the verified database backup. Prove recovered API behavior and preserved records. Failed recovery remains blocked, never reported as success.
7. Run an independent workload during planned upgrades: deterministic event IDs, a durable retry queue, acknowledged-event accounting, response hashes and database readback. Distinguish accepted, uncertain and rejected requests. Retries must not duplicate samples/verdicts. Measure downtime, retry latency, recovery time and lost/duplicated acknowledged events.
8. Export an operator report and sanitized HQ escalation bundle with exact versions, failed stage, diagnosis, attempted recovery, evidence and reproducible commands. Do not include environment dumps, secrets or raw production measurements.

## Acceptance scenarios (all remain in denominator)

- Fresh installation and duplicate installation refusal.
- Healthy rolling maintenance workflow with persistent input queue and verified no-loss recovery. This tool may use a documented maintenance window; it must not claim zero downtime.
- Successful backward-compatible schema + actual application release upgrade.
- Invalid migration SQL, lock timeout, startup failure and semantic API health failure.
- Controller termination after backup, during upgrade and after application start; reconcile and resume each.
- Concurrent upgrade refusal.
- Backup corruption / failed restoration blocks upgrade.
- Database unavailable, Redis unavailable and resource/missing-image preflight failures.
- Application rollback and database restore both verified through real API and complete authoritative record comparison.
- Repeated upgrades/recovery with at least 10,000 representative synthetic events and varying deterministic seeds. Report repetitions and failures; no scenario cherry-picking.
- Read-only diagnostics on a managed stack; absence of secrets in exported evidence.
- Owned test containers cleaned up, user stacks and database untouched.

Success requires zero lost acknowledged events and zero duplicated authoritative events/samples/verdicts, correct response semantics after recovery, bounded failure handling, and successful restore rehearsal. Performance limits are declared test targets with measured host/resources, not customer SLAs. Compare to a documented manual deployment baseline only where it answers an operational question.

## Formal and empirical evidence

Lean must model the actual operation state machine, allowed transitions and prerequisites (verified backup before destructive transitions, one owner, uncertain operation reconciliation). Proving a function that directly returns 'preserved=true' is not evidence of implementation safety. Formal invariants and empirical execution checks are reported separately. Do not push a completed release until both are reviewed with known gaps explicit.

## Deliberate product boundaries

Klarity KD/ACE licenses and customer environments are not available. Do not fabricate those integrations. PostgreSQL reference-stack success is not Oracle/PL-SQL compatibility. Support tools may be practical within the documented reference deployment while these vendor validation requirements remain unmet. Existing application behavior, dependency/image checks and all new failure paths require validation before publishing the improved release. Do not alter the already submitted application or send additional employer messages without a separate need.

## Release audit status

The exact-source acceptance result is `acceptance-results.json`: 22 passed,
0 failed and 0 unexecuted in this release suite. Historical failed/interrupted
attempts are separate and retained; see the README's development-failure table.

| Requirement | Authoritative verification |
|---|---|
| Database image admission | `guards` verifies wrong-image refusal before containers, volume or journal; unit tests cover missing, wrong and conflicting major metadata |
| Immutable runtime images | Acceptance image IDs match `security-results.json`; all three pass the recorded High/Critical gate |
| Invalid input and uncertain delivery | `queue-recovery` verifies rejection isolation, concurrent retries, conflict refusal, post-commit response loss and first-acknowledgement preservation |
| Existing application contracts | `app-regression` runs the existing HTTP/idempotency/transaction/Redis-fallback/mocks/metrics checks |
| Upgrade and recovery | Schema upgrade, startup/SQL/semantic/lock failures and six crash boundaries pass with verified original records |
| Large-workload accounting | Two independent seeded 10,000-event runs verify 240,000 measurements each with zero lost, duplicate or pending events |
| Resource cleanup | All 22 child runs recorded verified cleanup; no owned test container or volume remained at release verification |
| Source correspondence | Suite source hashes match the exported result; exporter refuses drift or incomplete evidence |
| Formal protocol | `formal-results.json` records 7/7 theorems and specification hash; `PROTOCOL_REVIEW.md` states runtime assumptions |
| Unit/export checks | `unit-results.json` records 33 passing tests and source hashes |

Publication is verified through the Git commit on the remote feature branch;
test success alone does not establish that a commit was published.

Image scan coverage includes actual packages: PostgreSQL has 46 SBOM components
and 45 scanned OS packages; Redis has 17 SBOM components and 16 scanned OS packages.
A zero finding count is not inferred from an empty report. Image findings do not
establish a complete host security approval or customer production readiness.

Failed and interrupted attempts remain in private evidence. They must be reported
separately from the final suite, never silently replaced with passing results.
Private MongoDB records, raw logs, credentials and local launchers are excluded
from publication.
