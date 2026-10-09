# Upstream test restoration progress

This is an in-progress audit, not a declaration that restoration is complete. Upstream snapshots and every reviewed/excluded source are recorded in `upstream-test-inventory.json`. YOFC and PLC4X test restoration is outside this task.

## Validated core batch

Maven 3.10 and JDK 21 have executed 912 test invocations across the modules below, including the previously restored JWT and existing migration protection tests. There are zero failures/errors and one platform assumption: the Linux/root-only clock update scenario is not executed on macOS. Counts describe the combined latest passing per-module reports, not one claimed full workspace run. Stale reports for removed test classes are excluded.

| Module | Tests | Skipped |
| --- | ---: | ---: |
| `kura/kura/emulator/org.eclipse.kura.emulator.position` | 2 | 0 |
| `kura/kura/emulator/org.eclipse.kura.emulator.watchdog` | 7 | 0 |
| `kura/kura/org.eclipse.kura.configuration.change.manager` | 15 | 0 |
| `kura/kura/org.eclipse.kura.core` | 109 | 0 |
| `kura/kura/org.eclipse.kura.core.certificates` | 13 | 0 |
| `kura/kura/org.eclipse.kura.core.comm` | 4 | 0 |
| `kura/kura/org.eclipse.kura.core.configuration` | 40 | 0 |
| `kura/kura/org.eclipse.kura.core.crypto` | 28 | 0 |
| `kura/kura/org.eclipse.kura.core.inventory` | 1 | 0 |
| `kura/kura/org.eclipse.kura.core.keystore` | 76 | 0 |
| `kura/kura/org.eclipse.kura.core.status` | 18 | 0 |
| `kura/kura/org.eclipse.kura.core.token.jwt` | 181 | 0 |
| `kura/kura/org.eclipse.kura.db.h2db.provider` | 13 | 0 |
| `kura/kura/org.eclipse.kura.db.sqlite.provider` | 31 | 0 |
| `kura/kura/org.eclipse.kura.driver.helper.provider` | 6 | 0 |
| `kura/kura/org.eclipse.kura.event.publisher` | 22 | 0 |
| `kura/kura/org.eclipse.kura.http.server.manager` | 3 | 0 |
| `kura/kura/org.eclipse.kura.json.marshaller.unmarshaller.provider` | 59 | 0 |
| `kura/kura/org.eclipse.kura.linux.clock` | 18 | 1 |
| `kura/kura/org.eclipse.kura.linux.usb` | 7 | 0 |
| `kura/kura/org.eclipse.kura.linux.watchdog` | 9 | 0 |
| `kura/kura/org.eclipse.kura.rest.identity.provider` | 21 | 0 |
| `kura/kura/org.eclipse.kura.rest.inventory.provider` | 11 | 0 |
| `kura/kura/org.eclipse.kura.rest.keystore.provider` | 20 | 0 |
| `kura/kura/org.eclipse.kura.rest.provider` | 22 | 0 |
| `kura/kura/org.eclipse.kura.rest.security.provider` | 5 | 0 |
| `kura/kura/org.eclipse.kura.rest.system.provider` | 5 | 0 |
| `kura/kura/org.eclipse.kura.util` | 47 | 0 |
| `kura/kura-unit-tests` | 119 | 0 |

Validation commands use the migration local repository configured for this workspace. The selections cover core unit modules and `:kura-unit-tests`; the three REST tail modules were rerun after adding their explicit test-only Gson/Jersey runtime dependencies.

## Adaptations

- JUnit 5 discovery replaces JUnit 4/TestCase, old extenders and PDE execution. Provided bundle imports are supplied explicitly on the Maven test classpath.
- `kura-unit-tests` is a test-only consumer of configuration, inventory and serializers, avoiding reverse dependencies/cycles in production bundles. It runs 82 configuration scenarios and 37 inventory scenarios.
- Configuration fixtures follow `updateIfDifferent`, DS arrival before runtime updates, last-list-PID registration, nonempty snapshots and preservation of corrupt XML as `.bad`.
- JSON decoder tests preserve the fork's custom metric-object parsing and use a genuinely unsupported nested object to test raw-body fallback. No production serialization change was made.
- NTP retry tests capture scheduler ticks instead of sleeping. Position and status tests clean up their schedulers. Linux executor tests cover both privilege variants using mocks only.
- GPIO methods and the deleted block driver/DriverServiceImpl tests are excluded entirely. Retained DriverDescriptorService, Linux LED/log notifications and process executor tests remain.

## Separate production fixes

- `ssl-default-keystore-fix.md`: historical null-file-path defect; upstream does not have it.
- `snapshot-file-permissions.md`: private snapshot permissions, retaining both encryption modes.
- Unknown status URLs default to NONE; missing session authentication leaves the audit context untouched.
- `crl-lazy-backport.md`: omitted upstream lazy CRL storage recovered and seven storage cases passed.

## Still in progress

The 13 CRL HTTP/download/refresh cases additionally pass through Failsafe with `-Posgi-it`, local random ports, isolated temporary files and bounded timeouts. The fixture waits for all CRL executors to terminate before removing its directory. Remaining real OSGi scenarios, sibling suites, IDEA JUnit invocation and full workspace acceptance are still to be completed.
