# Official OPC UA legacy server fixture audit

The three remaining sources were read in full at upstream `aee29e9f`. They are
recorded as `not-applicable-current-api` under the explicit instruction to keep
official OPC UA unchanged. This is a source applicability decision, not a passing
test result or a claim that OPC UA authentication/read/write needs no validation.

| Source | Scenarios and dependency |
| --- | --- |
| `CertificateAuthTest` | Four secure connection cases: Basic256Sha256 success, wrong application URI, disabled URI check and untrusted server certificate. Each starts an actual Milo server, creates certificates/JKS stores and obtains a Kura factory driver through the legacy OSGi test helper. |
| `OpcUaDriverTest` in `src/main/java` | Twenty container scenarios: service presence, connection, invalid-node read/write, signed/unsigned numbers, floating point, booleans, strings, byte values/arrays and a large numeric node ID. They require the embedded server and namespace; this is distinct from the already restored `src/test/java` class with the same simple name. |
| `TestNamespace` | Server-only helper deriving from ManagedNamespace, creating scalar/array nodes, implementing browse/read/write/method dispatch and subscription callbacks. No standalone test cases. |

Upstream's test POM pins Milo **0.6.16** and includes **sdk-server/stack-server**.
The current provider POM uses retained `p2.osgi.bundle` Milo **1.1.2** client/core/
transport artifacts; its handwritten manifest requires sdk-client, sdk-core,
stack-core and transport, with no server bundle. These fixture APIs cannot simply
be copied into that classpath. Restoring them would require a separate server API
migration and runtime arrangement, outside the current user-authorized scope.

No OPC UA repository file, dependency, OSGi metadata or driver behavior was changed.
Existing basic driver/descriptor tests and their recorded results remain intact.
The legacy secure-session and live server I/O scenarios were **not executed** and
are not replaced by the nine previously recorded basic client tests. No Milo 0.x
artifact or new server stack has been introduced. YOFC/PLC4X remain untouched.
