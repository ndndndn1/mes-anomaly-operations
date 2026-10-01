# Protocol-to-implementation review

This review maps the abstract Lean protocol to executable boundaries. It is not
a refinement proof. Runtime acceptance remains a separate requirement.

| Protocol boundary | Implementation | Runtime evidence required |
|---|---|---|
| One owner begins maintenance | `journal.host_lock` exclusive flock and `Journal.begin` revision compare-and-set | Concurrent-upgrade refusal, unchanged journal and records |
| Ingress closes during maintenance | `Controller.evaluate` shared lock plus installation/journal state check; request persisted before HTTP | Inputs queued across interruption and later replayed |
| Verified backup before candidate launch | `Controller.upgrade` ordered intents, dump checksum, isolated `verify_restore`, fingerprint comparison | Corrupt archive and restore failure prevent candidate start |
| Candidate validation | `Controller.semantic_probe` initial response, durable event, replay and child records | Healthy HTTP but corrupt semantics causes rollback |
| Uncertain operation requires reconciliation | `Journal.intent` refuses running/uncertain repetition; `Controller.recover` requires original operation | Six crash boundaries recover without blind candidate relaunch |
| Reopen only after validation | Readiness, fingerprint and semantic checks precede ready/completed records | Recovery preserves original records and queued inputs |

## Assumptions and limits

The Lean `backup`, `validate` and `restored` constructors represent external checks
that succeeded; Lean does not execute or prove those checks. Its owner is an
abstract operation identity. The operating-system lock, Docker ownership labels
and MongoDB revision checks implement separate runtime constraints and must be
tested independently. The same local engine, journal and protected credentials
must remain available. Cross-host coordination is not implemented.

A process may die between the ready installation update and journal completion.
`evaluate` additionally rejects ingress while that journal is unfinished. A
ready installation record alone therefore does not authorize delivery.

Journal completion can mean `rolled_back`. It does not mean that the proposed
release succeeded. Interrupted recovery records skipped/reconciled steps and a
separate verified recovery result; it does not turn unexecuted upgrade steps into
successful execution evidence.

The fingerprint covers the reference application's public-table records,
columns, constraints, indexes and sequence state. It does not cover every
PostgreSQL catalog object. API validation supplements that comparison but does
not establish vendor product compatibility.

## Evidence status

Seven abstract theorems compile with Lean 4.33.1. The complete 22-case empirical
suite passed on the source hashes in `acceptance-results.json`. This remains
reference-stack evidence, not a proof of the external implementation assumptions.
Failed, interrupted and unexecuted cases remain distinct from passing cases.
