# Verification strategy

JUnit tests cover detector semantics and strict cross-field validation. The Compose integration
runner exercises real Spring Boot, Flyway, PostgreSQL, and Redis instances plus deterministic
sensor/PLC/verifier doubles.

Concurrency sends eight identical requests simultaneously and requires one `201` plus seven `200`
replays with identical verdicts. Failure injection is test-profile-only and raises an exception
after both JDBC batches but before commit; retrying the same event must create it, proving rollback.
A second application instance points to an unreachable Redis port and must still create and replay
events, proving PostgreSQL authority and cache fallback.

CI also validates the frontend lockfile build, npm production audit, Compose configuration,
requirements coverage, scorecard structure, container build, dependency review, image
vulnerability policy, and runtime smoke.
