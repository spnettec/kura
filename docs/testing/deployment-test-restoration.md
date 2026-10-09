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
