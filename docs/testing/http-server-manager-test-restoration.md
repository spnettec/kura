# HTTP server manager restoration

All ten upstream scenarios pass under Jupiter: disabled listeners, one/three HTTP
ports, absent HTTPS keystore, HTTPS, mutual TLS, missing client certificate, missing
revocation sources, live CRL revocation, and simultaneous HTTP/HTTPS/mutual TLS.
The module reports 13 passing tests including its three existing connector tests.

The actual HttpService, JettyServerHolder, TLS factories and FilesystemKeystoreServiceImpl
run with per-test temporary storage and a private Equinox context. A test-only
BundleReference class loader gives manager classes their framework data directory;
it is not installed production-bundle or SCR wiring. Servlet dispatch and lifecycle
bindings are explicit. CryptoService and EventAdmin routing are controlled boundaries.
RSA certificates, PKCS12 stores, trust validation, Jetty connectors and CRL HTTP
downloads are real. Connections use bounded loopback requests; TLS settings are
per connection and do not change global SSL defaults.

The fork's keystore monitor and ten-second event-triggered restart remain unchanged.
Revocation first accepts the client, downloads a changed CRL, emits a keystore event,
restarts the actual manager, then rejects the same client. Negative cases require an
open listener and a server-side SSL handshake failure: client exceptions alone can
also represent a connection reset and are not the evidence of certificate rejection.

Each case stops Jetty, asserts listener closure and manager executor termination,
terminates keystore/CRL executors and stops Equinox. Tests do not use the host's
fixed ports or keystore. Maven 3.10.0 / Temurin 21, zero failures/errors/skips.
Full deployed SCR, Felix servlet bridge/configuration assembly and IDEA execution
remain open. Production code and handwritten OSGi metadata are unchanged.
