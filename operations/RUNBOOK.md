# Operator workflow

Scope: this repository's reference application on a local Linux Docker engine with scoped MongoDB/GridFS. No vendor product or customer-system compatibility is implied. Read the current security and acceptance status in [README](README.md) before using an image.

## Inputs and protected configuration

Install the pinned Python dependency in an isolated environment. Run commands from the repository root. The MongoDB account must be scoped to the selected operations database and its GridFS collections. Docker access is privileged: use only the intended local engine.

Provision `MESOPS_MONGO_URI`, `MESOPS_MONGO_DATABASE` and `MESOPS_DATABASE_PASSWORD` through the operator's existing protected environment/credential store. Persist the database password there for later recovery. Do not include it in the manifest, command arguments, repository or support bundle.

Build the reviewed images before resolving their immutable IDs:

```sh
docker build --target runtime -t mesops-runtime:local .
docker build -f operations/images/postgres.Dockerfile -t mesops-postgres:17 .
docker build -f operations/images/redis.Dockerfile -t mesops-redis:7 .
```

If your environment requires a proxy, supply its build proxy arguments and use a builder network that can reach it. Maven accepts optional `MAVEN_PROXY_OPTS`; do not put authenticated proxy credentials in build arguments. A build success does not replace the image vulnerability scan.

Create `deployment.json` with an installation name and the actual locally cached immutable image IDs:

```json
{
  "installation": "manufacturing-reference",
  "application_image": "sha256:REPLACE_WITH_ACTUAL_64_HEX_ID",
  "database_image": "sha256:REPLACE_WITH_ACTUAL_64_HEX_ID",
  "cache_image": "sha256:REPLACE_WITH_ACTUAL_64_HEX_ID",
  "database_major": 17,
  "drain_seconds": 30,
  "readiness_seconds": 120
}
```

The placeholders intentionally fail validation. Obtain IDs with `docker image inspect --format '{{.Id}}' IMAGE`. The controller never pulls images or adopts an unrelated container. It uses no host ports or WAN network for application workloads.

## Install and send inputs

```sh
python3 -m operations.control inspect --manifest deployment.json
python3 -m operations.control install --manifest deployment.json
python3 -m operations.control status --manifest deployment.json
```

Generate a current synthetic `event.json` using the first Python block in the
[API documentation](../docs/API.md), then send it through `evaluate` below. The
Compose HTTP curl example is separate from this isolated controller stack.

```sh
python3 -m operations.control evaluate --manifest deployment.json < event.json
```

Preserve the original event ID and exact payload when retrying. `queued:true` means durable acceptance into the controller queue, not completed application processing. Reusing an ID with changed content is rejected. Definitive HTTP 400/409/413/415/422 input rejection returns `rejected:true` and `http_status`; `evaluate` exits with code 2. Rejected records remain for audit and are excluded from automatic replay. Correct the input using a new event ID; never overwrite the old immutable payload. HTTP 429, authentication/service failures and lost responses remain pending instead of being reported as accepted or permanently rejected. Direct API writes bypass the controller's maintenance lock and are unsupported during managed maintenance.

## Upgrade, verify and replay

```sh
python3 -m operations.control backup --manifest deployment.json
python3 -m operations.control upgrade --manifest deployment.json --candidate-image sha256:ACTUAL_CANDIDATE_ID
python3 -m operations.control status --manifest deployment.json
python3 -m operations.control replay --manifest deployment.json --limit 100
```

A zero process exit code is not evidence that a candidate was promoted. Read `outcome`: `upgraded` means the validated candidate became current; `rolled_back` means the failed candidate was removed and the prior image/database restored. Retain the original manifest for interrupted-operation recovery. After successful promotion, use the returned updated manifest for subsequent operations.

Replay reports acknowledged, rejected and pending counts separately. One definitively invalid request does not prevent a later valid request from being processed. Repeat bounded replay until `pending` is zero. Do not interpret queue latency as application service latency: the benchmark includes the time waiting for an operator/test runner to start replay. The controller is a maintenance CLI, not an always-running input daemon.

## Interrupted operations

First read `status` and use its exact operation ID. Do not clear the journal or start a replacement upgrade.

```sh
python3 -m operations.control resume-install --manifest deployment.json --operation-id ACTUAL_OPERATION_ID
python3 -m operations.control recover --manifest deployment.json --operation-id ACTUAL_OPERATION_ID
```

Use `resume-install` only for installation. Use `recover` for unfinished backup/upgrade work, with the original manifest. Recovery returns to the prior release, verifies records and API behavior, then permits queued replay. It reconciles restore databases using persisted ownership reservations. It never removes databases merely because their names start with a prefix.

A corrupt/unrestorable backup keeps the operation unfinished and ingress closed. Preserve the journal, source database and blobs, collect diagnostics, and investigate before choosing a new recovery source. Do not fabricate a completion record or delete a damaged backup to make verification pass.

## Diagnosis and escalation

```sh
python3 -m operations.control diagnose --manifest deployment.json
python3 -m operations.control support-bundle --manifest deployment.json
```

These commands collect component state, immutable images, classified log codes, migration versions, lock contention and API health. The bundle includes reproduction commands and private evidence references, not credentials, raw logs or customer measurements. Review it before sending it to another organization; no upload is automatic.

| Finding | Operator interpretation and next action |
|---|---|
| `database_lock_contention` | Inspect transaction ownership. Do not kill arbitrary sessions. Upgrade failure evidence distinguishes lock timeout from invalid migration SQL. |
| `cache_unavailable` | Check the managed Redis process. PostgreSQL remains authoritative; degraded health alone does not prove a write was lost. |
| `database_not_running` | Preserve its named volume. Restore the managed DB process before attempting application readiness checks. |
| `dependency_namespace_mismatch` | Restarting the database namespace owner can leave app/cache peers on the old namespace. A controlled maintenance procedure must stop and recreate the owned peers in the current DB namespace, preserve the DB volume, and verify data/API before reopening writes. Automatic production repair of this condition is not yet exposed by the CLI; the isolated acceptance runner verifies the manual procedure. |
| Candidate health UP but validation failed | Inspect saved candidate evidence. A successful health endpoint does not prove persisted responses, replay behavior or business records are correct. |

## Evidence and limits

Operation journals, inputs, backup blobs, scratch reservations and verification attempts are retained in MongoDB/GridFS. The journal currently refuses more than 100 completed operations per installation until verified archival is implemented; it does not silently discard history.

Run [acceptance cases](ACCEPTANCE.md) in disposable installations, not by fault-injecting into an operator's existing stack. Never report a passing synthetic scenario as Klarity, Oracle, safety-system or customer production validation.

## Verification scope and unsupported recovery

Backup verification compares every row (including multiplicity) in every public
application table, column type/nullability/default, constraints, indexes and
sequence metadata/state, including `is_called`. This matches the reference
application schema. It is not a general PostgreSQL catalog equivalence checker:
functions, triggers, grants, extensions and every type modifier are not covered
by that fingerprint. A successful restore rehearsal must not be used as proof
that an arbitrary customer schema is equivalent. The reference application API
and repeat-request semantics are additional independent checks.

The supported recovery operation is recovery of an interrupted controller
installation or upgrade on the same local Docker engine, with its scoped MongoDB
journal, original manifest and protected database credential intact. Host loss,
MongoDB loss, cross-host disaster recovery and changes made outside the controller
are not validated recovery paths. Do not delete an unfinished journal to bypass
an unresolved recovery state.

The protocol proof assumes successful external verification and exclusive
ownership. It does not prove that Python, Docker, the operating system or the
database implement those assumptions. Consult the empirical acceptance results
separately from Lean's seven protocol theorems.

## Publish a synthetic acceptance report

After the complete matrix has reached `passed`, export its public fields with:

```sh
python3 quality/export_operations.py --suite-id ACTUAL_SUITE_ID --output operations/acceptance-results.json
```

The exporter uses the same protected MongoDB configuration as the controller.
It refuses a missing/failed/unexecuted case, unverified cleanup, changed source,
child-image mismatch or failed large-workload accounting. It omits internal run
IDs, installation names, database documents and arbitrary evidence fields.
The output file must not already exist; review an existing report explicitly
before replacing it. Scanner evidence and Lean results are separate gates, not
inferred from acceptance success. Review the resulting diff before publication.
