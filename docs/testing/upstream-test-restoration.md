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

### Networking core configuration continuation

Nineteen upstream core-network sources (15 suites and four fixtures) are reviewed.
The new suites pass 331 invocations: networking core.net 236, the core API firewall
configuration 21 and core util NetworkUtil 74. Core util reports 121 including 47
previous tests, which are not counted again. All runs use Maven 3.10.0 / JDK 21,
with zero failures/errors/skips and no host network changes.

Tests cover interface/address configuration, Wi-Fi/modem/IP interpreters, DHCP,
firewall serialization and address/MAC utilities. JUnit 4 expected exceptions and
method ordering become Jupiter assertions/order annotations. NetworkUtil and
FirewallConfiguration are intentionally retained in the local core util and API
modules; their inventory destinations and test packages now follow those actual
implementations. No production code, bundle manifest or DS metadata changed.

Current inventory: 210 restored sources, 23 restored helpers, 14 exclusions/replaced
harness entries and **218 unreviewed** out of 465. Networking still has 47 unreviewed
sources; Camel, Triton, management UI, deployment, remaining core tests and
real-container/transport/IDEA acceptance remain open.

### Networking Linux continuation

Twenty-one Linux network sources (19 suites and two helpers) are reviewed, with
132 restored invocations and five independently committed production regressions
passing under Maven 3.10.0 / JDK 21 / Jupiter. The regressions fix IPv6 save/restore
command selection and manual NAT removal during firewall reset. Temporary paths,
mocked commands, isolated lock files and bounded owned processes replace host
dependencies. Real serializer output and requested Wi-Fi capabilities are now
asserted, removing false-positive fallback logic from upstream tests.

See [Linux network audit](networking-linux-test-restoration.md) for validation,
preserved local ICMP/command/unblock behavior and the one excluded upstream-only
bulk-replace API scenario. Handwritten OSGi metadata is unchanged.

Current inventory: 229 restored sources, 25 restored helpers, 14 exclusions/replaced
harness entries and **197 unreviewed** out of 465. Networking has 26 sources still
unreviewed. This is not completion of the overall upstream restoration or IDEA /
real Equinox / Linux integration acceptance.

### Networking configuration and flooding protection continuation

Four more sources pass 42 invocations: firewall administration 13, network
configuration metadata 14, and flooding protection 15. All use Maven 3.10.0 /
JDK 21 / Jupiter, with zero failures/errors/skips. No production changes were
needed for this batch.

Firewall administration tests verify the fork's separate delete/add calls for
each rule family and continued event delivery after a family fails. They do not
introduce upstream's bulk-replace API; local IPv4 SSH/HTTPS safety defaults remain.
Rule lookup is by identity rather than HashSet iteration order. Flooding rules
retain the local additional IPv6 echo-reply DROP rule. Every fragment-threshold
path is redirected into a temporary directory, including configuration-only
scenarios that would otherwise probe `/proc`. The metadata test uses the actual
English/Chinese resource URLs through a mocked OSGi bundle and asserts the local
`%name` metadata key and two attributes.

The network definition has 189 attributes and 50 Wi-Fi attributes for the fixture.
It does not declare upstream's extra 802.1X password attribute. Existing modem and
Wi-Fi passphrase wrapping remains covered; an undeclared 802.1X property is
asserted to pass through unchanged, without adding that upstream feature.

Current inventory: 233 restored sources, 25 restored helpers, 14 exclusions/replaced
harness entries and **193 unreviewed** of 465. Networking has 22 remaining sources
(18 NetworkManager and four REST sources). Other siblings, remaining core sources,
and real-container/transport/IDEA acceptance are still open.

### NetworkManager lifecycle continuation

Ten additional upstream suites pass 47 new invocations. The complete current NM
module reports 1,035 passing invocations, including its 988 prior cases, under
Maven 3.10.0 / JDK 21 / Jupiter. Zero failures/errors/skips. See
[NetworkManager audit](networking-nm-test-restoration.md) for the controlled
scheduler, temporary-file, NMEA and D-Bus boundaries. No production or handwritten
OSGi metadata changed.

Current inventory: 243 restored sources, 25 restored helpers, 14 exclusions/replaced
harness entries and **183 unreviewed** of 465. Networking has eight NM and four REST
sources remaining. Other siblings, remaining core sources and real-container /
transport / IDEA acceptance are still open.

### NetworkManager status and configuration continuation

Four additional suites pass 253 new invocations, and the full current NM module
passes 1,288 with no failures/errors/skips under Maven 3.10.0 / JDK 21 / Jupiter.
Two further source entries require APIs absent from this fork and are marked
not-applicable-current-api. See [NetworkManager audit](networking-nm-test-restoration.md).
No production source or handwritten OSGi metadata changed.

Current inventory: 247 restored sources, 25 restored helpers, 16 exclusions/replaced
harness entries and **177 unreviewed** of 465. Networking still has two NM sources
and four REST sources; the broader sibling/core and runtime/IDEA work remains open.

### NetworkManager settings converter continuation

One fully reviewed source adds 153 passing cases. The complete NM module passes
1,441 invocations under Maven 3.10.0 / JDK 21 / Jupiter, without failures, errors
or skips. See [NetworkManager audit](networking-nm-test-restoration.md) for corrected
negative-branch fixtures and preserved local D-Bus/conversion behavior.

Current inventory: 248 restored sources, 25 restored helpers, 16 exclusions/replaced
harness entries and **176 unreviewed** of 465. Networking still has its connector
and four REST sources; remaining sibling/core and real runtime/IDEA acceptance
are open. No production source or handwritten OSGi metadata changed in this batch.

### NetworkManager connector continuation

The connector adds 49 applicable passing invocations; four upstream-only Reapply
scenarios are excluded explicitly. The complete NM module passes 1,490 with no
failures/errors/skips under Maven 3.10.0 / JDK 21 / Jupiter. Current D-Bus 5.2.0,
Update/ActivateConnection and virtual-thread behavior are preserved. See
[NetworkManager audit](networking-nm-test-restoration.md) for the bus boundary and
remaining runtime acceptance. No production source or handwritten metadata changed.

Current inventory: 249 restored sources, 25 restored helpers, 16 exclusions/replaced
harness entries and **175 unreviewed** of 465. Networking has four REST sources
remaining; other sibling/core sources and real runtime/IDEA acceptance remain open.

### Separate NetworkManager failure-path repair

Five new regressions reproduced state-listener leaks in failed connection update,
creation, physical/VLAN activation and disconnect operations. The production fix
scopes DeviceStateLock cleanup independently of whether waiting starts. All 1,495
NM invocations now pass, including 54 connector cases. The five failure cases
failed on the original production code and pass after the repair. Source inventory
counts remain unchanged at **175 unreviewed**. See the [NM audit](networking-nm-test-restoration.md).

### Networking REST component continuation

The four remaining networking sources (two suites and two helpers) were reviewed.
47 component scenarios pass: configuration 12 and status 35, using the actual
request proxy, JSON conversion and exception mapping with mocked service boundaries.
The original HTTP authorization scenario and HTTP/MQTT/DS transport matrix remain
explicitly deferred in the inventory. See [networking REST audit](networking-rest-test-restoration.md).

Current inventory: 251 restored sources, 27 restored helpers, 16 exclusions/replaced
harness entries and **171 unreviewed** of 465. Networking has no unreviewed source
entries, but its real D-Bus/Linux/HTTP/MQTT/DS/IDEA acceptance is unfinished. Core
125, Triton 15, Camel 14, deployment 7, management UI 7 and official OPC UA 3 remain
unreviewed; official OPC UA stays unchanged as requested.

### Camel continuation

All 14 Camel source entries were reviewed and restored: 12 suites plus two helpers.
52 Jupiter cases pass under Maven 3.10.0 / JDK 21, including real XML routes and
registered type conversion on the existing Camel 4.20.0. See the
[Camel audit](camel-test-restoration.md) for lifecycle, Future and assertion
adaptations and the remaining OSGi/runtime acceptance.

Current inventory: 263 restored sources, 29 restored helpers, 16 exclusions/replaced
harness entries and **157 unreviewed** of 465. No production source or handwritten
OSGi metadata changed. Core 125, Triton 15, deployment 7, management UI 7 and
official OPC UA 3 remain unreviewed; official OPC UA stays unchanged as requested.

### Triton managers, configuration and encryption continuation

Six more sources add 80 passing Jupiter cases against current production APIs.
The fixtures own their schedulers and temporary files, and mock only the external
command/container boundary. See [Triton audit](triton-test-restoration.md).

Current inventory: 269 restored sources, 29 restored helpers, 16 exclusions/replaced
harness entries and **151 unreviewed** of 465. Triton still has nine source entries;
core, deployment, management UI and runtime/IDEA work remain open. Official OPC UA
remains unchanged. No production or handwritten metadata changed in this batch.

### Separate Triton resource-option equality repair

Three regressions reproduced CPU/memory/GPU Optional reference comparisons that
made repeated configuration values unequal. Value comparisons now preserve the
existing no-change update guard. The original three cases failed; the fixed full
module passes 83 tests. See [Triton audit](triton-test-restoration.md). This is a
separate production fix; the source inventory remains **151 unreviewed**.

### Triton service and gRPC continuation

Nine remaining Triton sources (seven suites/two helpers) add 30 passing scenarios.
The complete module passes 113 including the three separate equality regressions.
Actual in-process gRPC and localhost HTTP verify serialization, inference values and
metrics; external command/container services are mocked. See [Triton audit](triton-test-restoration.md).

Current inventory: 276 restored sources, 31 restored helpers, 16 exclusions/replaced
harness entries and **142 unreviewed** of 465. The remaining source revisions are
core 125, deployment 7, management UI 7 and official OPC UA 3. Core-origin sources
include tests now owned by cloud/container siblings. Official OPC UA remains
unchanged, and runtime/IDEA acceptance is still unfinished.

### Separate Triton gRPC lifecycle repair

Actual-channel regressions showed configuration updates retained the old gRPC
connection, including updates to invalid configuration. The old channel now closes
and terminates before reconfiguration; unchanged configuration keeps its channel.
Two negative regressions failed before the fix. The complete module passes 116
cases after it. Source inventory remains **142 unreviewed**. See [Triton audit](triton-test-restoration.md).

### Deployment download and install continuation

Two more sources add 22 passing Jupiter cases; core.deployment passes 53 in total.
Fixtures use isolated files and require actual checksum failures and package
installation work. See [deployment audit](deployment-test-restoration.md).

Current inventory: 278 restored sources, 31 restored helpers, 16 exclusions/replaced
harness entries and **140 unreviewed** of 465. Deployment still has five sources;
core-origin, management UI, official OPC UA and runtime/IDEA work remain open.
Official OPC UA remains unchanged.

### Separate deployment I/O failure notification repair

Two regressions reproduced COMPLETED notifications after missing input or failed
artifact persistence. IOException now reaches the existing FAILED notification
path. Both failed before the fix; the complete core.deployment module passes 55
cases afterward. See [deployment audit](deployment-test-restoration.md). Source
inventory remains **140 unreviewed**.

### Deployment HTTPS continuation

Four real TLS scenarios and the adapted download resource bring core.deployment
to 59 passing cases. JDK 21 hostname rejection is preserved even when the SSL
manager flag is false; the contrary upstream expectation is explicitly adapted.
See [deployment audit](deployment-test-restoration.md). No production TLS changes.

Current inventory: 279 restored sources, 32 restored helpers, 16 exclusions/replaced
harness entries and **138 unreviewed** of 465. Deployment has three sources left;
core-origin, management UI, official OPC UA and runtime/IDEA work remain open.

### Deployment agent continuation

Seventeen restored scenarios pass on current executor-based install/uninstall and
actual local Marketplace HTTPS parsing; the complete agent module passes 28 cases.
See [deployment audit](deployment-test-restoration.md). No production changes.
Current inventory is 280 restored sources, 32 helpers, 16 exclusions/replaced
harness entries and **137 unreviewed** of 465. Deployment has two sources left.

### Deployment packages HTTP REST continuation

All 12 upstream REST scenarios now execute real Jersey HTTP and multipart parsing;
the complete packages REST module passes 31 cases. Runtime auth/OSGi remain open.
See [deployment audit](deployment-test-restoration.md). No production changes.
Current inventory is 281 restored sources, 32 helpers, 16 exclusions/replaced
harness entries and **136 unreviewed** of 465. Deployment has one source left.

### Cloud deployment handler continuation

All 53 annotated scenarios (including three formerly ignored configuration tests)
now pass; core.deployment passes 112 cases. Static state/executor ownership and
actual Future completion replace shared-state/sleep assumptions. See
[deployment audit](deployment-test-restoration.md). No production changes.

Current inventory: 282 restored sources, 32 helpers, 16 exclusions/replaced harness
entries and **135 unreviewed** of 465. Deployment has no unreviewed sources; remaining
origins are core 125, management UI 7 and official OPC UA 3. Official OPC UA remains
unchanged. Source auditing and runtime/IDEA acceptance are still not complete.

### Management UI audit context and enum continuation

Reused and reviewed the existing ConsoleTest; restored ScaleOffsetTypeTest in the
existing Java 21 test module. All 13 cases pass while production Web2/GWT remain
Java 11. See [management UI audit](management-ui-test-restoration.md).
Current inventory: 284 restored sources, 32 helpers, 16 exclusions/replaced harness
entries and **133 unreviewed** of 465. Five UI sources remain.

### Separate Web2 Modem password placeholder repair

One of four restored upstream scenarios exposed a literal placeholder being stored
when the previous interface was not a Modem. The separate repair preserves local
configuration lookup and YOFC networking; full Web2/GWT build and 17 test cases pass.
See [management UI audit](management-ui-test-restoration.md). Inventory: 285 restored
sources, 32 helpers, 16 exclusions/replaced harness entries and **132 unreviewed**.
Four UI sources remain; official OPC UA and runtime/IDEA acceptance remain unchanged.

### Separate Web2 configuration password placeholder repair

Eight upstream scenarios and four caller/local-behavior checks pass after seven
negative regressions. All configuration conversion callers preserve unset passwords;
explicit clearing, stored secrets and local metadata/lookup conventions remain.
Web2/GWT build and 29 cases pass. See [management UI audit](management-ui-test-restoration.md).
Inventory: 286 restored sources, 32 helpers, 16 exclusions/replaced harness entries
and **131 unreviewed**. Three UI sources remain; runtime/IDEA work remains open.

### Separate Web2 metatype default rendering repair

Two restored sources and a localized rendering regression add 10 passing cases;
six failed before the separate default decoding/copy repair. All 39 UI cases and
Web2/GWT build pass, retaining the local locale-aware path and Java 11 production
target. See [management UI audit](management-ui-test-restoration.md). Inventory:
288 restored sources, 32 helpers, 16 exclusions/replaced harness entries and
**129 unreviewed**. LogServlet is the final UI source pending audit.

### Web2 log ZIP continuation and separate repair

Eight applicable upstream ZIP/name scenarios plus two local regressions pass after
six negative failures. Seven upstream-only archive-name/private-temp-directory
scenarios are explicitly excluded to preserve local behavior. All 49 UI tests and
Web2/GWT build pass. See [management UI audit](management-ui-test-restoration.md).
Inventory: 289 restored sources, 32 helpers, 16 exclusions/replaced harness entries
and **128 unreviewed**: 125 core-origin and 3 official OPC UA. UI source audit is
complete; runtime, authorization and IDEA acceptance remain open. OPC UA unchanged.

### Container configuration/descriptor continuation

Four restored sources pass 21 cases, preserving local disabled defaults and
enforcement keys. Two sources require absent token-file/automatic-activator APIs
and are explicitly not applicable; no features imported. See
[Container audit](container-test-restoration.md). Inventory: 293 restored sources,
32 helpers, 18 exclusions/replaced harness entries and **122 unreviewed**. Six
Container sources, other core-origin sources, official OPC UA and runtime/IDEA work
remain open.

### Container command failure and allowlist continuation

Two restored sources add 11 passing cases (including local digest fallback);
all 32 orchestration tests pass. The identity-integration source's 19 scenarios
require absent local APIs and are explicitly not applicable. No production changes.
See [Container audit](container-test-restoration.md). Inventory: 295 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **119 unreviewed**. Three
Container sources and the remaining core-origin/OPC UA/runtime/IDEA work remain.

### Container orchestration service continuation

Twenty-one service scenarios pass after correcting obsolete keys and weak fixtures;
the orchestration module passes 53 cases without daemon access or production changes.
See [Container audit](container-test-restoration.md). Inventory: 296 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **118 unreviewed**. Two
Container sources remain; other core-origin, official OPC UA and runtime/IDEA work
continue to be open.

### Container instance options continuation

All 57 upstream scenarios plus a local empty-properties case pass (58 total).
Typed CPU fixtures and equality/hash checks are corrected without production changes.
Identity exclusion wording now distinguishes the existing signature-digest
ConfigurationService binding from absent identity/Token APIs. See
[Container audit](container-test-restoration.md). Inventory: 297 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **117 unreviewed**. Container
lifecycle, other core-origin sources, official OPC UA and runtime/IDEA work remain.

### Container instance lifecycle continuation

Twenty lifecycle/signature scenarios pass with executor barriers and signature
persistence assertions. The full Container bundles reactor passes 131 cases with
no production changes. See [Container audit](container-test-restoration.md).
Inventory: 298 restored sources, 32 helpers, 19 exclusions/replaced harness entries
and **116 unreviewed** (113 core-origin and three official OPC UA). All 12 Container
sources have been audited; real runtime/IDEA acceptance and other sources remain.

### Cloud options, schedule and factory continuation

Three sources pass 19 cases with no production changes. Scheduling tests now
exercise the disconnect race deterministically; factory fixtures preserve local
PID/reference/i18n behavior and explicitly exclude three wrong-prefix assumptions.
See [Cloud audit](cloud-test-restoration.md). Inventory: 301 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **113 unreviewed**. Other
Cloud/core sources, official OPC UA and runtime/IDEA acceptance remain open.

### Cloud modem device-profile continuation

Two sources add six passing cases against current NetworkStatusService DTOs and
real address parsing, with no direct D-Bus or production changes. See
[Cloud audit](cloud-test-restoration.md). Inventory: 303 restored sources, 32 helpers,
19 exclusions/replaced harness entries and **111 unreviewed**. Source audit and
real runtime/IDEA acceptance continue; official OPC UA unchanged.

### Kapua options and lifecycle payload continuation

Four sources add 49 cases; all 52 current Kapua tests pass. Weak/shared fixtures and
tamper enumeration are corrected without production changes. See
[Cloud audit](cloud-test-restoration.md). Inventory: 307 restored sources, 32 helpers,
19 exclusions/replaced harness entries and **107 unreviewed**. Source/runtime/IDEA
work remains open; official OPC UA unchanged.

### Kapua Protobuf builder continuation

Three sources restore 37 upstream cases plus one binary Unicode round-trip;
all 90 current Kapua cases pass without production or dependency-version changes.
See [Cloud audit](cloud-test-restoration.md). Inventory: 310 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **104 unreviewed**.
Remaining source audit, real runtime and IDEA acceptance remain open.

### Kapua lifecycle publication continuation

Two sources restore 17 scenarios with controlled 30-second scheduling and actual
message acknowledgements; all 107 Kapua cases pass. See [Cloud audit](cloud-test-restoration.md).
Inventory: 312 restored sources, 32 helpers, 19 exclusions/replaced harness entries
and **102 unreviewed**. A scheduler deactivation defect is isolated for separate
regression/fix; remaining source/runtime/IDEA work is still open.

### Separate Kapua delayed-publisher lifecycle repair

Three negative-confirmed deactivation regressions now pass: timer cancellation,
executor shutdown and queued-task guards prevent work against cleared bindings.
All 110 Kapua cases and isolated bundle installation pass. See
[Cloud audit](cloud-test-restoration.md). Source inventory remains **102 unreviewed**;
this repair does not stand in for remaining source/runtime/IDEA work.

### Kapua publisher continuation

Three sources add nine passing message/registry contract tests; all 119 Kapua cases
pass. The DS service-existence scenario remains explicitly deferred in the inventory.
See [Cloud audit](cloud-test-restoration.md). Inventory: 315 restored sources,
32 helpers, 19 exclusions/replaced harness entries and **99 unreviewed**. Real
DS/MQTT/IDEA acceptance remains open alongside remaining source audit.

### Kapua client and service API continuation

Two sources restore 27 cases with observable listener/binding checks and isolated
lifecycle fixtures; all 146 Kapua tests pass. See [Cloud audit](cloud-test-restoration.md).
Inventory: 317 restored sources, 32 helpers, 19 exclusions/replaced harness entries
and **97 unreviewed**. Kapua's remaining CloudService integration source and other
source/runtime/IDEA work remain open.

### Kapua birth metrics and connection facade continuation

The final Kapua source adds 12 business cases using actual JSON encoding and current
modem/tamper DTOs; the original real MQTT/DS pipeline is explicitly deferred. All
158 Kapua cases pass and all 16 source files are reviewed. See
[Cloud audit](cloud-test-restoration.md). Inventory: 318 restored sources, 32 helpers,
19 exclusions/replaced harness entries and **96 unreviewed**. Other source audit,
real runtime and IDEA acceptance remain open.

### Sparkplug endpoint and subscription continuation

Five sources plus a shared helper restore 25 passing cases, preserving local
virtual-thread behavior and correcting weak equality/connection fixtures. See
[Cloud audit](cloud-test-restoration.md). Inventory: 323 restored sources, 33 helpers,
19 exclusions/replaced harness entries and **90 unreviewed**. Remaining source
audit, runtime and IDEA acceptance are still open.

### Separate Sparkplug listener cleanup

A negative-confirmed regression now verifies listener removal after disconnect on
endpoint deactivation. All 26 Sparkplug tests and isolated bundle installation pass.
See [Cloud audit](cloud-test-restoration.md). Inventory remains **90 unreviewed**;
source/runtime/IDEA work continues.

### Sparkplug transport options and configuration continuation

Two sources add 33 passing cases; all 59 Sparkplug tests pass. An upstream no-op
assertion is explicitly excluded. Local password and lifecycle behavior is retained.
See [Cloud audit](cloud-test-restoration.md). Inventory: 325 restored sources,
33 helpers, 19 exclusions/replaced harness entries and **88 unreviewed**. Source,
real runtime and IDEA acceptance remain open.

### Sparkplug factory and Protobuf continuation

Two sources plus a helper add 60 passing cases; full Sparkplug module passes 119.
Factory tests preserve local PID/i18n behavior; Protobuf cases now assert actual
encoded types. See [Cloud audit](cloud-test-restoration.md). Inventory: 327 restored
sources, 34 helpers, 19 exclusions/replaced harness entries and **85 unreviewed**.
Remaining source audit, runtime and IDEA acceptance continue.

### Sparkplug subscriber continuation

One source restores six cases with exact asynchronous delivery and complete payload
checks; all 125 Sparkplug tests pass. See [Cloud audit](cloud-test-restoration.md).
Inventory: 328 restored sources, 34 helpers, 19 exclusions/replaced harness entries
and **84 unreviewed**. Source/runtime/IDEA acceptance continues.

### Sparkplug real MQTT continuation

Two test sources restore 23 loopback MQTT cases and replace one legacy fixture source.
All 148 Sparkplug tests pass; all 15 Sparkplug source files are reviewed. See
[Cloud audit](cloud-test-restoration.md) for the real-broker boundary and deferred SCR/
persistence/TLS/IDEA work. Inventory: 330 restored sources, 34 helpers, 20 exclusions/
replaced harness entries and **81 unreviewed**. Overall restoration is still ongoing.

### Separate Sparkplug service-reference repair

Two negative-confirmed regressions verify release on tracker close and service
unregistration. All 150 Sparkplug cases and isolated installation pass. See
[Cloud audit](cloud-test-restoration.md). Inventory remains **81 unreviewed**;
remaining source/runtime/IDEA work continues.

### DataService storage and reconnect continuation

One source restores all 20 scenarios with observable in-flight/queue behavior and
controlled reconnect scheduling. All 30 Cloud Base tests pass. See
[Cloud audit](cloud-test-restoration.md). Inventory: 331 restored sources, 34 helpers,
20 exclusions/replaced harness entries and **80 unreviewed**. Source, runtime and
IDEA work remains open.

### Cloud connection REST continuation

One source restores 14 distinct endpoint scenarios through actual routing, JSON and
service lookup logic; all pass. Original transport/authentication/runtime assembly
remains deferred. See [Cloud audit](cloud-test-restoration.md). Inventory: 332 restored
sources, 34 helpers, 20 exclusions/replaced harness entries and **79 unreviewed**.
Source/runtime/IDEA acceptance continues.

### Separate cloud REST reference repair

Eight negative-confirmed regressions cover acquired service release on normal calls
and connection failures across both manager routes. All 22 REST tests and isolated
installation pass. See [Cloud audit](cloud-test-restoration.md). Inventory remains
**79 unreviewed**; source/runtime/IDEA acceptance continues.

### Cloud Base real MQTT/TLS continuation

One source restores 17 scenarios plus one custom-factory regression using actual
TLS/WSS/mutual authentication and revocation validation. Eight failures exposed a Paho
hostname-policy override, fixed in a separate production commit. All 48 Cloud Base
tests and isolated installation pass. See [Cloud audit](cloud-test-restoration.md)
for service/runtime boundaries. Inventory: 333 restored sources, 34 helpers,
20 exclusions/replaced harness entries and **78 unreviewed**. Source/runtime/IDEA
acceptance continues.

### Separate MQTT lifecycle repair

Two negative-confirmed cases verify exactly-once client release on repeated
deactivation, with and without a preceding disconnect. All 50 Cloud Base tests and
isolated installation pass. See [Cloud audit](cloud-test-restoration.md). Inventory
remains **78 unreviewed**; source/runtime/IDEA acceptance continues.

### H2/SQLite message-store and SQLite source audit

The 28 upstream store contracts run against each actual database; one shared source
and two provider fixtures replace the old OSGi test target. The existing SQLite
Jupiter sources were checked for full-suite compatibility, and temporary-property
pollution was fixed. Their inventory entries were already restored. Full modules
pass 41 H2 and 59 SQLite cases. See [Database audit](database-test-restoration.md).
Inventory: 334 restored sources, 35 helpers, 20 exclusions/replaced harness entries
and **76 unreviewed**. The three separate SQLite runtime test sources remain pending. Source/runtime/IDEA acceptance continues.

## Cloud SQL/MQTT continuation (2026-10-10)

The last three Cloud source entries now have audit dispositions: shared fixture,
seven DataService scenarios and one CloudService workflow using real SQL/MQTT/Protobuf.
Cloud Base 57 tests/install and Kapua 159 tests pass with zero failures/errors/skips.
See `cloud-test-restoration.md` for mocked boundaries and the Moquette `$`-prefix limit.
Actual SCR/Equinox and IDEA acceptance remain open.

Current inventory: 465 entries, 336 restored, 36 restored helpers, eight replaced
legacy harnesses, six current-API exclusions, six removed-functionality exclusions
and **73 unreviewed**. These are source-file dispositions, not invocation counts.

## SQLite persistence continuation (2026-10-10)

Sixteen actual SQLite persistence/maintenance cases and six debug-query cases pass;
the complete module reports 81 tests with zero failures/errors/skips. Three upstream
sources are audited, including their shared fixture. Native extraction in actual OSGi
and Gogo command assembly remain deferred; see `database-test-restoration.md`.

Current inventory: 465 entries, 338 restored, 37 restored helpers, eight replaced
legacy harnesses, six current-API exclusions, six removed-functionality exclusions
and **70 unreviewed**. Source audit is not runtime or IDEA acceptance.

## OSGi utility continuation (2026-10-10)

Nine tracker and three generic bundle-filter tests run on an actual isolated Equinox
framework. Full util suite: 133 passing tests, zero failures/errors/skips. Four
GPIO-specific cases are excluded. A newly identified tracker service-usage leak will
be handled separately; see `osgi-util-test-restoration.md`.

Current inventory: 465 entries, 340 restored, 37 restored helpers, eight replaced
legacy harnesses, six current-API exclusions, six removed-functionality exclusions
and **68 unreviewed**. Kura SCR/IDEA acceptance is still open.

The OSGi tracker leak is now repaired in a separate production commit. Three
negative-confirmed Equinox lifecycle cases pass, as do all 136 util tests and isolated
installation. No metadata or ranking semantics changed; inventory remains 68 unreviewed.

## Event and role-store continuation (2026-10-10)

Two event publication scenarios and all ten role-store methods pass; current module
reports are 24 and ten tests, zero failures/errors/skips. Role storage uses real Felix
roles with controlled scheduler/event/configuration boundaries. Event helper/worker
lifecycle defects will be repaired separately. See `event-useradmin-test-restoration.md`.

Current inventory: 465 entries, 342 restored, 37 restored helpers, eight replaced
legacy harnesses, six current-API exclusions, six removed-functionality exclusions
and **66 unreviewed**. Runtime SCR and IDEA acceptance remain open.

Event publisher lifecycle repair is now validated separately: three negative-confirmed
regressions plus the full 27-test suite and isolated installation pass. Replaced helpers
and deactivated virtual-thread executors close correctly. Inventory remains 66 unreviewed.

## System service continuation (2026-10-10)

Both upstream sources are audited: five configuration/package cases and 26 runtime
property cases pass on Maven 3.10/JDK 21/Jupiter. Two hardcoded legacy-path cases and
actual SCR registration remain explicitly deferred; two no-op cases are excluded.
See `system-service-test-restoration.md`. No production changes.

Current inventory: 465 entries, 344 restored, 37 restored helpers, eight replaced
legacy harnesses, six current-API exclusions, six removed-functionality exclusions
and **64 unreviewed**. Deferred methods, runtime and IDEA acceptance remain open.

## Core platform continuation (2026-10-10)

Two more core sources restore three invocations: primary MAC discovery for `eth0`
and `en0`, and positive uptime parsing. Full core/system suites pass 111 and 32
cases respectively. Actual service registration and host hardware remain deferred.
See `system-service-test-restoration.md`; a suspected uptime units defect is isolated
for separate confirmation and repair.

Inventory: 346 restored, 37 helpers, 20 exclusions/replaced harnesses and **62
unreviewed** out of 465 source entries. Runtime and IDEA acceptance remain open.

The macOS uptime mismatch is now repaired separately. One negative-confirmed
regression plus all 33 system tests and isolated installation pass. No network,
API or metadata changes; inventory remains 62 unreviewed.

## Identity continuation (2026-10-10)

One test source and one fixture restore 71 identity/permission/password/extension
scenarios; the full module passes 87 tests. A temporary-identity source and two
methods requiring absent local APIs are explicitly excluded. No production or
metadata changes. See `identity-test-restoration.md` for fixture boundaries.

Inventory: 346 restored, 38 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **59 unreviewed** out of 465.
Actual runtime, authentication and IDEA acceptance remain open.

## REST JWT HTTP continuation (2026-10-10)

Five scenario sources and five helpers restore 32 real loopback HTTP cases across
Jetty/Jersey, REST filters, identity/role logic and RSA token issuance/verification.
Full REST provider module: 54 passing tests. Replay checks also prove that the
expired token is still independently verifiable within clock-skew tolerance.
See `rest-jwt-test-restoration.md` for remaining SCR/storage/whiteboard boundaries.

Inventory: 351 restored, 43 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **49 unreviewed** out of 465.
Other sources, actual Kura runtime and IDEA acceptance remain open.

## REST password-change continuation (2026-10-10)

The upstream session-continuity scenario and an additional identity-collision
regression both reproduced a production defect. Separate fix `bdd42b9f6a` keeps
the replacement session bound to its authenticated username. All 56 REST provider
tests and isolated installation pass; see `rest-password-session-fix.md`.

Inventory (recounted from JSON): 352 restored, 43 helpers, eight replaced harnesses,
eight current-API exclusions, six removed-functionality exclusions and **48
unreviewed** out of 465. The preceding identity/JWT prose counts are corrected to
match their JSON entries; no previous disposition changes. Actual Kura runtime and
IDEA acceptance remain open.

## REST authentication continuation (2026-10-10)

All 63 methods in `RestServiceTest` pass over actual loopback HTTP and mutual TLS.
They exercise authentication, permissions, session/XSRF/cookie behavior, password
policy, banners, audit IP and errors. Full module: 119 passing tests. See
`rest-authentication-test-restoration.md` for lifecycle and assembly boundaries.

Inventory: 353 restored, 43 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **47 unreviewed** out of 465.
All REST provider source entries are audited; actual Kura runtime and IDEA acceptance
remain open.

## Shared request fixture continuation (2026-10-10)

Five request/JSON helper sources are migrated to the plain Maven test-support
artifact. Six real-HTTP/JSON checks and isolated installation pass. Assertions now
reject 3xx success and missing-current-cookie rotation false positives. See
`request-test-support-restoration.md`; concrete MQTT and OSGi discovery remain open.

Inventory: 353 restored, 48 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **42 unreviewed** out of 465.
Endpoint integration, actual Kura runtime and IDEA acceptance remain open.

## Identity endpoint continuation (2026-10-10)

The opt-in endpoint module restores all nine V1 and sixteen V2 scenarios over real
HTTP and MQTT: 50 passing invocations, including cleanup. Shared fixture test JARs
avoid duplicate IDEA source roots. See `identity-endpoint-test-restoration.md`.

Inventory: 355 restored, 49 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **39 unreviewed** out of 465.
Actual Kura SCR/runtime and IDEA acceptance remain open.

## System and tamper endpoint continuation (2026-10-10)

All upstream tamper and system endpoint scenarios pass over HTTP and MQTT: 18 and
24 invocations respectively. System fixture export also passes its five existing
tests plus install. See `system-tamper-endpoint-test-restoration.md`.

Inventory: 357 restored, 49 helpers, eight replaced harnesses, eight current-API
exclusions, six removed-functionality exclusions and **37 unreviewed** out of 465.
Actual Kura SCR/runtime and IDEA acceptance remain open.
