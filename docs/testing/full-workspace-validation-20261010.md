# Full workspace test validation — 2026-10-10

`RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 ./build-all.sh -nsu` completed successfully
at 11:01:10 Asia/Shanghai using Maven 3.10.0, Temurin JDK 21, and the isolated
`migration-m2` repository. All source repositories were clean on
`codex/maven-bundle-idea`; their exact revisions are recorded in the
[machine-readable evidence](full-workspace-validation-20261010.json).

The build installed public build support, core bundles, every required sibling,
the existing YOFC applications, core distribution packages, and the development
runtime. Docker was explicitly disabled for this test regression; this run does
not replace the separately recorded Docker or Linux GUI acceptance.

## Current-source results

399 fresh class/nested-class XML reports contain **5,280 test invocations:
5,271 passed, nine skipped, zero failures and zero errors**. A report is counted
only when its timestamp belongs to this build and its fully qualified class name
matches an existing Java source. Nested classes map to their enclosing source;
repeated dependency/reactor executions count once per repository/module/class.
No fresh report was excluded for a missing source. Stale reports from earlier
builds are not included.

| Repository | Tests | Skipped |
| --- | ---: | ---: |
| kura | 1,887 | 3 |
| kura-networking | 1,961 | 0 |
| kura-cloud | 400 | 0 |
| kura-wires | 380 | 0 |
| kura-deployment | 171 | 0 |
| kura-container | 131 | 0 |
| kura-triton | 116 | 0 |
| kura-position | 75 | 0 |
| kura-camel | 52 | 0 |
| kura-management-ui | 49 | 0 |
| kura-opcua | 9 | 0 |
| yofc-iot (existing tests) | 49 | 6 |

Core includes **65 real Equinox tests** and **397 HTTP/MQTT endpoint tests**, all
passing without skips. These are included in the total, not added a second time.
Networking retains the fork's dbus-java 5.2.0/virtualthreads and Update/Activate
behavior; this run does not exercise a host NetworkManager/D-Bus connection.

The three core skips are the two explicitly gated hardcoded system-path methods
and the Linux/root clock update. The system-path methods separately passed in the
isolated Linux fixture (35 tests, no skips); see
[system service restoration](system-service-test-restoration.md). The six YOFC
skips remain the existing physical PLC, serial, network device, VISA and external
database cases. No YOFC/PLC4X tests or official OPC UA server functionality were
added for this validation.

## Evidence and remaining scope

Before Linux IDEA can replace shared `target` outputs, the build log, all 399 XML
reports, report collector and summary were copied to the local archive:
`/Users/heyoulin/iot-kura-develop/migration-baseline/full-restoration-20261010`.
The JSON records each report's path and SHA256, the build log checksum, and the
source revision combination. The archive is not committed with personal data.

Inventory dispositions remain 369 restored, 60 helpers, 18 replaced harnesses,
12 not applicable, six excluded and zero unreviewed. This successful full build
does not close the explicitly deferred SCR/transport/hardware scenarios, Linux
GUI Run/Debug acceptance or P7 cleanup/CI/template work.
