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

## Further validated batches

- Core identity: 16 password-policy cases now run against the service directly, including configuration updates. Two upstream username-aware password cases require a public API this fork does not contain; they are recorded as excluded methods rather than silently enabled against different semantics or introducing a business API during test restoration.
- XML inventory/configuration serialization: eight cases run in the cross-module consumer. Both previously disabled OCD scenarios now use an explicit descriptor fixture, preserving the fork's snapshot behavior of omitting the descriptor while retaining properties. The consumer now reports 127 cases.
- Position sibling: 67 serial/GPSd/parser/tracker/service cases and eight REST cases pass. Fixtures use the current `CommConnectionFactory` contract, classpath resources and explicit thread/provider cleanup; all hardware endpoints are mocked.
- OPC UA sibling: nine basic driver/descriptor cases pass against Milo 1.1.2, adapted from upstream 0.6.16 APIs. Stable IDs and localized names are checked separately. YOFC's independent PLC4J OPC UA integration is outside this restoration; old server/OSGi test fixtures are not claimed as passing or compatible.
- Deployment sibling: 61 options, hook, download, marketplace and REST cases pass. A separate fix configures the Kura SSL factory before requesting an HTTPS response; a negative test run confirms the old order fails the assertion.
- Networking sibling: 988 parameterized enum/property/status cases pass. Jupiter method sources and nested suites replace the old JUnit 4 runners. Upstream-only modem APIs are recorded explicitly, and the fork's existing unmanaged/disabled interface behavior is preserved.
- Wires sibling: 129 asset/cloudlet/REST, AI, publisher/subscriber, regex, database and script cases pass; three further channel-record cases run in the retained core asset module. Service trackers and Graal contexts are closed, H2 databases are isolated, and upstream optional/dynamic position scenarios are explicitly excluded from the fork's mandatory/static DS contract. No production source or descriptor was changed in this batch.

Every batch uses Maven 3.10 and JDK 21. These counts are separate module reports and are not added to repeated dependency-module runs as a claimed workspace-wide total.

## Separate production fixes

- `ssl-default-keystore-fix.md`: historical null-file-path defect; upstream does not have it.
- `snapshot-file-permissions.md`: private snapshot permissions, retaining both encryption modes.
- Unknown status URLs default to NONE; missing session authentication leaves the audit context untouched.
- `crl-lazy-backport.md`: omitted upstream lazy CRL storage recovered and seven storage cases passed.

## Still in progress

The 13 CRL HTTP/download/refresh cases additionally pass through Failsafe with `-Posgi-it`, local random ports, isolated temporary files and bounded timeouts. The fixture waits for all CRL executors to terminate before removing its directory. Remaining real OSGi scenarios, sibling suites, IDEA JUnit invocation and full workspace acceptance are still to be completed.

At the requested session pause on 2026-10-09, the source inventory has 465 entries: 181 restored sources, 11 restored helpers, six removed-functionality exclusions, six replaced legacy harness entries, one upstream-only API entry and 260 unreviewed sources. These are source-file audit counts, not test invocation counts. No entry is left in an in-flight adapting state.

## Wires continuation: graph, asset and FIFO (2026-10-09)

Eight more upstream source entries have been reviewed: six test sources and two
component fixtures. They add 62 passing invocations: graph CRUD/wire creation 6,
WireAsset read/write and timestamp modes 6, FIFO 2, asset errors 6, change cache 6,
and scale/offset across read and event modes 36. The two selected modules report
77 passing invocations including 15 previously restored cases; those 15 are not
counted again as new coverage. Maven 3.10.0 / JDK 21, zero failures/errors/skips.

- Asset fixtures use the current `asset.component` class, explicit OCD defaults,
  local `request.timeout` and the single-`WireRecord` normal-output contract.
- Error/cache/scale assertions run against real component logic with a recording
  driver and mocked WireSupport. They replace the old graph/OSGi harness at the
  component layer and do not claim new Equinox integration coverage.
- FIFO tests hold the consumer while filling the queue, use ordered sequence
  envelopes, and join the emitter after deactivation. Asset configuration waits
  and executor termination are bounded; fixed sleeps and permanent latch waits
  are removed. Graph tests close the service tracker after each case.
- The cleanup assertions exposed a separate production defect, fixed in
  `a0e23034ce`: [asset listener unregistration](asset-listener-unregistration.md).
  Its two core regression cases are separate from the 62 restored invocations.

Current inventory: 465 entries, 187 restored, 13 restored helpers, six
removed-functionality exclusions, six replaced legacy harness entries, one
upstream-only API entry, and **252 unreviewed**. Timer, database/REST graph and
remaining real-container fixtures still need review; IDEA and final migration
acceptance remain open.

### Timer continuation

The ten upstream Timer scenarios also pass. Deterministic scheduling captures verify
initial delay, 10/100 ms intervals, fixed-rate selection, old-worker shutdown on
update, no immediate default tick and custom first-tick delay. Real executor ticks
and receiver exceptions run through `WireHelperServiceImpl`; valid Cron and recovery
from invalid Cron use the real RAM-backed Quartz scheduler with only the service
registry boundary mocked. Cleanup joins the captured Quartz threads, waits for
simple executors, and verifies clock-event service unregistration. This is component
coverage, not an Equinox/ConfigurationAdmin test.

The component module now reports 81 passing invocations (10 newly restored). The
inventory is now 188 restored sources, 13 restored helpers, 13 exclusions/replaced
harness entries, and **251 unreviewed** out of 465. Remaining Wires database, asset
and REST graph sources, other repositories and IDEA acceptance are still open.

### Database continuation

Eight upstream database sources (five suites and three helpers) are now reviewed.
The database component module passes 148 invocations: 130 newly restored and 18
previous cases, with zero failures/errors/skips under Maven 3.10.0 / JDK 21.
H2 and SQLite exercise WireRecordStore/Query; H2 additionally exercises the legacy
DbStore/Filter. Each invocation starts an isolated database, closes connections,
and terminates the database executors. Configuration, column-type transitions,
null/unsupported values, cache expiry, record limits, ID monotonicity and the legacy
1200-to-1104 cleanup sequence retain their functional assertions.

The old MEDIAN unsupported-type assumption conflicts with this fork's intentional
BigDecimal-to-Double conversion. Timestamp now exercises unsupported values and
explicit casting; a separate assertion protects the existing MEDIAN result.
The legacy receive scenario checks the actual TIMESTAMP column instead of column 1
(which is ID). Cache expiry keeps SQL unchanged and checks record counts before
and after aging the cache, avoiding both fixed sleeps and configuration-driven
cache invalidation. The old registration-only `testSvcs` check is replaced by
fixture startup checks; this batch does not claim new Equinox coverage.

Current source inventory: 193 restored, 16 restored helpers, 13 exclusions/replaced
harness entries and **243 unreviewed**, out of 465. Wires asset/REST graph sources,
other sibling/core suites, real-container scenarios and IDEA acceptance remain open.

### Core Asset continuation

The Wires upstream AssetTest now runs in the retained core asset bundle: all 27
scenarios pass, with both driver/descriptor helpers restored and the JUnit 4 suite
wrapper replaced by Jupiter discovery. The module reports 32 passing invocations
including five previous regression/helper cases; zero failures/errors/skips.

The fixture uses real BaseAsset executors and logic, explicit driver arrival/removal
at the registry boundary, five-second configuration barriers, propagated callback
assertion failures and executor termination checks. Metadata assertions preserve
this fork's request.timeout and channel description/unit fields (123 attributes),
and the read-all assertion addresses a named channel rather than relying on map
iteration order. No production or handwritten OSGi metadata changed.

Inventory: 194 restored sources, 18 restored helpers, 14 exclusions/replaced harness
entries and **239 unreviewed**, out of 465. The two Wires REST graph sources still
need review, as do remaining core/sibling suites and real OSGi/IDEA acceptance.

### Wires REST graph continuation

All 49 upstream endpoint scenarios now pass through the real JaxRsRequestHandlerProxy,
JSON codec and WireGraphServiceImpl. The configuration service and registry/SCR
boundaries are controlled doubles. Tests check graph CRUD, validation, configuration
requests, PID filtering and metadata DTOs; original service-arrival checks are
replaced by assertions on requested configurations. No HTTP server, MQTT broker or
Equinox DS lifecycle is claimed. Those transport/container acceptance checks remain
open and are explicitly listed on the inventory entry.

Expected asset metadata keeps the fork's localization keys, description field and
existing DataType options. The old malformed trailing comma was removed from the
not-in-graph update request so its 400 assertion exercises membership validation.
Upstream JsonProjection and ChannelDescriptorTestDriver test utilities are adapted
locally with their licenses; driver/definition inputs are independent of expected
response JSON. No production or handwritten OSGi metadata changed.

Maven 3.10.0 / JDK 21: 49 passing REST cases and six previously restored graph
cases, zero failures/errors/skips. Inventory: 195 restored sources, 19 restored
helpers, 14 exclusions/replaced harness entries and **237 unreviewed** of 465.
All Wires snapshot source entries have now been reviewed at the documented layers;
remaining repositories and real-container/transport/IDEA acceptance are still open.
