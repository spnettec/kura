# Security endpoint restoration

All eight V1 and seven V2 upstream scenarios run over real HTTP and MQTT in the
opt-in endpoint module: 16 + 14 = 30 passing invocations, zero failures/errors/skips.

V1 covers security/command-line fingerprint reload, debug status, unauthenticated
HTTP rejection, MQTT behavior, an authenticated identity with no extra permission,
and provider failures mapped to 500. Reload cases additionally verify the actual
SecurityService boundary call. Strong fixture passwords retain production policy.

V2 covers default and supplied policy application, both fingerprint reloads, provider
failure, null/empty input and the original oversized request (3.6 MB before payload
encoding). Invalid requests must not call SecurityService. The test-only broker
limit is 8 MiB so the encoded request reaches the actual endpoint's 1 MiB rejection
branch rather than being dropped by Moquette's 8092-byte default. Cloud fixture hook
is committed as kura-cloud `591fea6`, with its 57 tests and installation passing.
Other broker fixtures retain their defaults; no production broker limit changed.

SecurityService is mocked; these tests do not write live security policy files or
reload the host's fingerprints. Actual HTTP authentication, JAX-RS request dispatch,
MQTT request/reply correlation and shared bounded resource cleanup are exercised.
The upstream Windows-only assumption on oversized input is retained; on this macOS
run both transport invocations executed and passed.

Validation: Maven 3.10.0 / Temurin 21, isolated repository, Failsafe `verify` selecting
the two security classes. Mac IDEA direct class Run also passed V1 16/16 and V2
14/14; see `mac-idea-rest-endpoints-validation-20261010.json`. Full deployed Kura
SCR/configuration assembly and actual security-policy file application require
an external actual SecurityService provider: official Kura HEAD contains only
the API, optional REST consumer and mock-backed tests. See
`security-service-upstream-audit-20261011.md`. Policy-file application remains
unverified. No production security behavior, handwritten metadata,
YOFC/PLC4X, D-Bus or OPC UA changed.
