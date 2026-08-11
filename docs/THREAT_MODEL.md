# Threat model and scope boundaries

Protected assets are event identity, sensor history, limits, verdict integrity, and database
availability. Primary mitigations are bounded inputs, strict JSON decoding, finite-number checks,
transactional idempotency, parameterized SQL, non-root/read-only containers, dropped capabilities,
resource ceilings, localhost-only host publication, dependency audits, and image scanning.

This reference does not implement authentication, authorization, tenant isolation, TLS, secrets
rotation, rate limiting, or an Internet-facing ingress. Those controls must be supplied by the
deployment environment. The service must remain behind a trusted, authenticated boundary.

There is intentionally no equipment command API, OPC-UA client, Modbus client, or safety interlock.
The PLC test double exposes status only. A verdict is operational decision support and must never
bypass a safety-rated controller or human approval process.
