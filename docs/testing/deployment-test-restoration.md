# Deployment upstream test restoration

2026-10-09; upstream snapshot `kura-deployment@6b403dbd`.

## Download and install continuation

DownloadImplTest (10 cases) and InstallImplTest (12 cases) were fully reviewed and
restored on Jupiter. The complete core.deployment module passes 53 tests, zero
failures/errors/skips under Maven 3.10.0 and Temurin JDK 21 with migration-m2.
No production or handwritten OSGi metadata changes in this batch.

All installation, persistence, verifier and download files use per-test TempDir
paths. The callback's unused legacy componentOptions setup was removed; download
options explicitly select the test directory. Negative checksum cases now require
KuraException and deletion instead of passing when their catch block was never
entered. Unsupported-protocol assertions surround only the download operation.

The successful installation fixture creates a real input file and supplies the
mock DeploymentPackage version. It verifies deployment-admin invocation, the moved
artifact and persisted package entry. Previously it could pass on a missing input
without invoking deployment admin. Script execution and deployment-admin boundaries
remain mocked; real file handling and notification payloads are exercised. File
readers are closed. Only Log4j API was added to test scope.

Five deployment source entries remain unreviewed, including actual HTTP download
and REST integration, the cloud handler and deployment agent. Runtime/OSGi/IDEA
acceptance remains open.

## Separate production repair: do not report file I/O failure as completed

Two regressions reproduced COMPLETED notifications when the input artifact did
not exist and when the installed artifact could not be moved to its persistence
path. installDeploymentPackageInternal logged IOException and returned normally,
so installDp sent a completion message even if deployment admin was never called.

The caught IOException now propagates to installDp's existing failure notification
path. The tests assert FAILED, zero progress and a nonempty error, distinguishing
missing-input/no-admin-call from a persistence failure after admin installation.
Both failed on the original code and pass after the one-line production repair;
the complete module passes 55 tests, zero failures/errors/skips. Existing package
cleanup and deployment-admin behavior are unchanged. This does not add rollback
for a persistence failure after deployment admin has installed a package.

## HTTPS download continuation

DownloadImplITTest and DownloadTestRestService are reviewed and restored as four
Jupiter transport cases and one helper. The full core.deployment module passes 59
cases, zero failures/errors/skips. Certificates, keys and the truststore are built
in memory; downloads use TempDir; the server binds localhost on an OS-selected port.
The production downloader, SSLSocketFactoryWrapper and SslManagerServiceImpl perform
the actual handshake. Only the OSGi/keystore service boundaries are mocks. The
fixture owns and stops its server/executor, cancels the completed download worker
for cleanup, and restores the downloader's global redirect setting afterward.

Two cases download the complete upstream text fixture (trailing whitespace normalized) with a trusted localhost certificate,
with the SSL manager hostname flag both true and false. Two reject a trusted
certificate whose name does not match localhost, requiring a hostname-specific
failure notification, no completed notification, no HTTP request and no install.
The upstream test expected the false flag to permit a mismatched certificate.
That expectation fails under the current JDK 21 HttpsURLConnection, which retains
its own hostname verification. Current behavior is preserved; no permissive
HostnameVerifier or production TLS changes were introduced.

The first attempt exposed a stale core artifact in migration-m2 containing the
already-fixed default-keystore bug. Installing the current core bundle resolved
that setup issue; the earlier repair was not duplicated. The helper serves the
fixture bytes via an owned JDK HTTPS server instead of a DS/JAX-RS registration.
Actual configuration-service updates, REST routing and OSGi service wiring remain
runtime acceptance work. Three deployment source entries remain unreviewed.
