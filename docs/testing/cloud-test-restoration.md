# Cloud upstream test restoration

2026-10-09; core-origin sources pinned to kura@e500a68d. Clean local Cloud branch
codex/maven-bundle-idea verified before editing. Project knowledge vault is not
registered; existing kura-doc session/plan remain the handoff context. Local
CloudConnection/i18n, handwritten metadata and production behavior are preserved.

## Data options, schedule and default factory

Three sources pass 19 cases (4 options + 6 schedule + 9 factory), zero failures,
errors or skips on Maven 3.10.0/JDK 21/Jupiter. Only test-scope Jupiter/Mockito
dependencies are added to two existing bundles. No production modifications.

Options fixtures now actually change DB PID and republish flag; inactivity seconds
use Long as required by the local API. Assertions also verify rate units, cron,
inactivity and default maximum payload. Schedule tests use a controlled executor
and fixed UTC time; the public constructor uses a scoped scheduler-factory mock,
so no scheduler thread leaks. The disconnect-race case actually enters disconnect,
queues a priority message and verifies the second connection attempt. Teardown
verifies timeout cancellation, shutdown and termination wait, replacing upstream
minor-delay calls and ineffective disconnected-state assertions.

Factory tests preserve local timestamp-generated data/transport PIDs, configuration
reference links, final cloud snapshot, service.factoryPid selection, arbitrary cloud
PID and Chinese name/description. Three upstream wrong-prefix rejection/ignore
scenarios do not apply: the local factory accepts custom PIDs and resolves linked
configuration targets. These scenarios are explicitly listed in the inventory;
three local cases cover that behavior instead. Six applicable upstream scenarios
remain covered. No upstream suffix-derived PID or marker-property behavior imported.

Remaining Cloud source audit, real MQTT/DS/Equinox and IDEA acceptance remain open.

## EclipseIoT and Kapua modem profile continuation

Both upstream sources pass all three scenarios each: Ethernet + modem IP, absent
NetworkStatusService and modem without an address. Real current API status builders
and IPAddress parsing are used with mocked service boundaries. Test-only Guava
supplies the API's non-transitive provided address-parsing dependency. No direct
D-Bus calls, old NetworkManager interfaces, network changes or production changes.
Six cases pass on Maven 3.10.0/JDK 21/Jupiter, zero failures/errors/skips. This checks
profile construction, not real modem/D-Bus/OSGi connectivity.

## Kapua options and lifecycle payload continuation

Four sources add 49 passing cases: CloudServiceOptions 28, CloudPublisherOptions 9,
KuraBirthPayload 10 and KuraDisconnectPayload 2. The complete current Kapua module
passes 52 cases, zero failures/errors/skips on Maven 3.10.0/JDK 21/Jupiter. Production
unchanged. Birth/disconnect payload tests consume the existing shared API artifact.

Per-test option fixtures replace mutable BeforeClass state. The non-string encoding
case now writes payload.encoding rather than topic.control-prefix; the primitive
QoS default is asserted exactly instead of a vacuous not-null assertion. Scoped
assertThrows replaces JUnit 4 expected. Jupiter Nested/EnumSource replaces Enclosed
and Parameterized runners, covering all three tamper values including NOT_TAMPERED
(previously omitted in favor of duplicate UNSUPPORTED). Lifecycle defaults, position,
JDK metadata, rendering and disconnect body copy are verified.

## Protobuf builder continuation

Three sources restore all 37 upstream payload/metric/position builder cases plus
one Unicode binary round-trip, 38 passing cases. Null failures use scoped
assertThrows; metric and position merges now compare complete merged values as
well as presence bits. Payload merge ordering, scalar types, clearing and required
fields are covered. Existing Protobuf 4.29.3-generated source and 4.30.2 runtime are
unchanged. Generated-file graph parse coverage is absent; targeted source reads
confirmed the concrete builders. The complete Kapua module passes 90 cases on
Maven 3.10.0/JDK 21/Jupiter, zero failures/errors/skips. No production changes.

## Birth/APPS/DC publishing and device-profile continuation

Two sources restore 17 cases: 15 lifecycle publication scenarios and two position
profile scenarios. The full Kapua module passes 107 cases, zero failures/errors/skips
on Maven 3.10.0/JDK 21/Jupiter. Production unchanged in this restoration commit.

A scoped scheduler-factory mock captures the actual 30-second request; assertions
check no early publication before explicitly running its task, then verify topic,
QoS, retain and priority. The old 25-second/no-QoS-0 check was ineffective. Immediate
messages use actual onMessagePublished acknowledgements on an owned virtual-thread
executor with termination assertions. Updates follow activation, unregister cases
remove a real registered handler, and teardown deactivates the service. Position
radians-to-degrees and absent service remain covered. Shared production callback
executor is untouched. No real MQTT/Equinox or wall-clock timing claim.

Source audit found that deactivate leaves the per-instance birth scheduler/pending
task alive. Test cleanup currently owns its fake scheduler explicitly. This
production lifecycle defect will be verified and repaired in a separate commit.

## Separate delayed-publisher deactivation repair

Three new regression scenarios failed before the fix: pending cancellation and
scheduler shutdown were absent, and an already-dequeued task accessed cleared
SystemAdminService and threw NPE. Deactivation now serializes cancellation/shutdown
with delayed publishing before clearing bindings. Both scheduling and queued-task
execution check scheduler shutdown; existing immediate disconnect publication,
30-second coalescing, QoS and the shared callback executor are unchanged.

All 18 BirthMessages cases and 110 Kapua module cases pass, zero failures/errors/skips
on Maven 3.10.0/JDK 21/Jupiter. The repaired bundle is packaged/installed into the
isolated migration-m2 repository. Production fix is committed separately from
restoration. Runtime DS/MQTT acceptance remains open.

## Publisher and notification continuation

Three sources add nine passing cases (publisher registry/business four, absent-cloud
one, notification four); full Kapua module passes 119 cases, zero failures/errors/skips
on Maven 3.10.0/JDK 21/Jupiter. Test-only Log4j API supplies KuraException's existing
provided dependency. Production unchanged.

Real ServiceTracker runs against a mocked BundleContext with real LDAP filters.
Activation, update and close exercise the actual customizer and current virtual-thread
worker lifecycle. QoS 0/1 forwarding asserts complete message properties and payload
identity; notification checks the exact topic/control/priority map. Failure checks
use scoped assertions and SERVICE_UNAVAILABLE codes. The old static DS/latch service
existence assertion is explicitly deferred for real Equinox/SCR validation; ordinary
JVM tracking does not claim actual factory/configuration/MQTT integration.

## CloudClient and CloudService API continuation

Two sources restore all 27 upstream cases (22 client + 5 service); the complete
Kapua module passes 146 tests, zero failures/errors/skips on Maven 3.10.0/JDK 21/
Jupiter. No production modifications. Client binding and listener add/remove are
asserted through actual forwarding/callback behavior rather than private-field
inspection; publication topic/priority, subscriptions, queue IDs and callback
arguments remain covered. Fresh service activation/deactivation replaces static
shared fixtures and releases its scheduler. Configuration retrieval now verifies
the configured prefix in addition to object presence.

## CloudService legacy integration-source audit

All 13 upstream scenarios audited. Twelve business scenarios now pass as ordinary
Jupiter tests: connect failure propagation, 10-second disconnect delegation, info
forwarding, notification PID, CPU/extended properties, tamper absence/state/event
republishing and single/multiple-modem selection. Actual CloudService publication
uses the existing shared JSON encoder via a test-scope bundle dependency; assertions
parse real encoded bytes and verify MQTT topic/QoS/retain/priority at the mocked
DataService boundary. Tamper events use controlled 30-second scheduling and actual
acknowledgement callbacks with owned executor termination. Current modem/SIM DTOs
are used; no D-Bus imports or network implementation changes.

The original service-existence assertion and real Moquette/MQTT, CryptoService,
ConfigurationService and EventAdmin/DS pipeline remain explicitly deferred. No
fixed-port broker is launched by these tests. Full Kapua module passes 158 cases
with zero failures/errors/skips on Maven 3.10.0/JDK 21/Jupiter. All 16 Kapua source
files have now been reviewed; real MQTT/Equinox/IDEA acceptance remains open.

## Sparkplug endpoint and subscription continuation

Five test sources and their shared StepsCollection restore all 25 upstream cases:
record equality six, subscription matching/removal seven, delivery callbacks two,
connection/event callbacks six and DataService facade four. All pass with zero
failures/errors/skips on Maven 3.10.0/JDK 21/Jupiter. Jupiter/Mockito are test-only
dependencies; production/OSGi metadata unchanged.

Symmetric equality now checks both directions; invalid assumptions requiring
different hashes for unequal objects are removed. Connected state assertions now
check returned false/true values. Fixtures deactivate every endpoint and close the
current virtual-thread executor; activation exceptions no longer disappear into an
unasserted field. MQTT wildcard/QoS matching uses the actual local Paho matcher.
Real MQTT/DS/IDEA acceptance remains open.

## Separate Sparkplug endpoint listener cleanup

A new negative regression confirms that endpoint deactivation previously retained
its DataService listener. A separate production fix unregisters the endpoint after
disconnect and before its existing virtual-thread executor shutdown. Ordering is
asserted. All 26 current Sparkplug cases pass and isolated bundle installation
succeeds on Maven 3.10.0/JDK 21; no metadata changes. Real DS/MQTT remains open.

## Sparkplug transport options and configuration continuation

Two sources add 33 cases: all 29 parameter scenarios plus four meaningful lifecycle
scenarios. The upstream `test()` containing only `assertTrue(true)` is explicitly
excluded. All 59 Sparkplug tests pass with zero failures/errors/skips on Maven
3.10.0/JDK 21/Jupiter. Production unchanged; test-only Log4j API supplies the existing
KuraException provided dependency.

Nested/parameterized fixtures assert exact ordered server lists, mandatory option
errors and the current String password/CryptoService path. Real unconnected MQTT
client objects exercise SSL-manager rebinding and ordered updating/updated callbacks;
teardown deactivates the transport. No broker or network connection is opened.
Real MQTT/DS/IDEA acceptance remains open.

## Sparkplug factory and Protobuf type continuation

Two test sources and one shared helper add 60 passing cases: factory nine, Protobuf
51. Full Sparkplug module passes 119 cases, zero failures/errors/skips, on Maven
3.10.0/JDK 21/Jupiter. Production and handwritten OSGi metadata unchanged.

Factory scenarios preserve arbitrary endpoint PIDs, timestamp child PIDs, Chinese
name/description fields, target-based lookup excluding the endpoint, and one final
snapshot. Six upstream cases remain applicable; the wrong-prefix rejection case is
explicitly excluded. Three added cases cover custom metadata and null/empty generated
endpoint PIDs. No upstream suffix-derived IDs or factory marker is imported.

The upstream type tests called inference rather than the explicit-type overload and
never checked encoded datatype. Fixtures now use Byte/Short/BigInteger correctly and
assert the encoded type and value, including unsigned upper limits. All 38 upstream
scenarios are retained, with 13 additions for DateTime, eleven inferred Java types
and an actual binary/Unicode serialization round trip. Generated protobuf sources
and library versions are unchanged. Real MQTT/DS/IDEA acceptance remains open.

## Sparkplug subscriber continuation

All six upstream scenarios pass: wildcard routing, unsubscription, reconnect
subscriptions and three connection callbacks. Fixtures activate/deactivate real
subscriber trackers against an empty mocked registry and retain actual virtual-thread
executors. Graceful endpoint-then-subscriber draining makes message counts exact;
teardown asserts executor termination. Every decoded scalar/binary metric, body,
timestamp and sequence is checked, replacing the original three-field matcher.

All 125 Sparkplug tests pass, zero failures/errors/skips on Maven 3.10.0/JDK 21/Jupiter.
Production unchanged; real MQTT/DS/IDEA acceptance remains open.

## Sparkplug real loopback MQTT continuation

Sixteen transport and seven device scenarios now pass through actual Moquette 0.18.0
and Paho sockets on a random loopback port. The old static JUnit 4/SCR harness is
replaced by Jupiter fixtures; broker persistence and telemetry are disabled. Client,
broker and owned virtual-thread dispatchers are closed. Random reconnect jitter is
controlled while production transport, protocol state machine and wire payloads run.

Negative STATE/NCMD cases explicitly subscribe the otherwise unmatched topic, ensuring
messages reach the production handler. Dispatcher barriers precede negative assertions.
Connection failure uses loopback port zero rather than external DNS. Device tests use
real endpoint/device/ServiceTracker with a forwarding mock only at the DataService
persistence boundary. Changed-metric and reconnect tests now require the second DBIRTH
with correct sequences and payload; the upstream atLeastOnce matcher could pass on the
first message alone.

Moquette's getPort races its asynchronous bind-listener HashMap update, observed as
ConcurrentModificationException on the second test class. A bounded startup-readiness
wait handles only this third-party port-reporting race; failed test assertions are not
retried. Full Sparkplug module passes 148 cases, zero failures/errors/skips on Maven
3.10.0/JDK 21/Jupiter. Production and handwritten OSGi metadata unchanged. Test-only
Moquette uses the upstream version/repository and excludes its old logging backend.

All 15 Sparkplug source files are reviewed. The original shouldBeSetup SCR/factory
service-discovery assertion, complete DataService persistence pipeline, TLS/authentication
and actual IDEA/Equinox runtime acceptance remain explicitly deferred.

## Separate Sparkplug tracker reference repair

Two regression cases failed before the fix: closing the tracker and receiving an
UNREGISTERING event both retained the acquired endpoint service reference. The
customizer now releases it in a finally block after the removal callback. Actual
ServiceTracker tests verify exactly one release even after subsequent close.

This production change is separate from restoration. All 150 Sparkplug cases pass,
including the 23 real loopback MQTT cases, and isolated bundle installation succeeds
on Maven 3.10.0/JDK 21. No OSGi metadata or i18n changes. Real SCR/persistence/TLS/IDEA
acceptance remains open.

## DataService implementation continuation

All 20 upstream cases pass through actual activation, updates and public callbacks.
Captured scheduling replaces the old 3/8/20-second sleeps, and a controlled publisher
boundary keeps storage assertions deterministic. Every fixture deactivates and checks
executor shutdown; the production one-second shutdown wait is retained.

In-flight restoration is checked by confirming the restored transport token and
observing the original stored ID/topic, replacing private-field reflection. Cases
cover payload thresholds, negative priority, new-session drop/republish failures,
configuration changes, message-store connection events and queue-specific regexes.
The watchdog test executes ten connection failures explicitly and verifies exactly
eight checkins (initial + three authentication + four ordinary failures), preserving
local recovery behavior. Test-only Log4j API supplies the existing KuraException
provided dependency. All 30 Cloud Base cases pass with zero failures/errors/skips
on Maven 3.10.0/JDK 21/Jupiter. Production unchanged; real persistence/runtime/IDEA
acceptance remains open.

## Cloud connection REST continuation

All 14 distinct upstream endpoint scenarios pass once through the actual request
proxy, JSON request/response mapping, CloudConnectionService/manager bridge and real
LDAP matching against a mocked OSGi registry. Assertions check exact PID sets,
configuration contents, factory/pubsub mutations and both connection states, replacing
non-empty-only checks. Fixtures use arbitrary local PIDs and explicit linked children,
without assuming upstream suffix-derived identifiers.

Jupiter, Mockito, Gson, Jersey runtime delegate, Log4j API and OSGi Promise are
scope-test dependencies. Promise supplies the SCR interface's previously excluded
transitive type; the initial missing-class failure was only a test classpath issue.
Maven 3.10.0/JDK 21 reports 14 tests, zero failures/errors/skips. Production unchanged.
The original HTTP/MQTT transport matrix, authenticated HTTP roles and real SCR/factory/
ConfigurationService assembly remain explicitly deferred, not counted twice as mock
transport runs.

## Separate REST bridge service-reference repair

Eight regression cases failed before the fix: connect/disconnect/status and connection
failure retained acquired DataService or CloudConnectionManager references. The bridge
now releases each acquired service in finally, including exception paths. It no longer
ungets CloudService metadata references or unmatched managers that were never acquired.
Local suffix matching, legacy priority, disconnect timeout and error translation remain
unchanged. All 22 REST cases and isolated installation pass on Maven 3.10.0/JDK 21.
This production repair is committed separately; no OSGi metadata changes.

## MQTT TLS restoration and separate hostname-policy repair

Seventeen upstream scenarios now use real Paho, Moquette 0.18.0, TLS/WSS sockets,
Kura SSL manager and PKIX validation with temporary in-memory certificates. Both
brokers bind loopback port zero. The fixture reads Moquette's actual bound WSS port
(no public accessor) instead of reserving and releasing a port. It closes broker,
SSL trackers and retained Paho resources. KeystoreService is the mocked boundary,
supplying real KeyStore, KeyManager and CertStore objects.

Both formerly ignored missing-client-key cases now run against a broker requiring
mutual TLS with the client CA configured. Wrong-truststore cases retain a valid client
key so they exercise server trust. Unbinding a separate truststore is tested after a
successful connection. Revocation first connects with a valid CRL, then rejects the
revoked broker after actual SSL cache invalidation. The upstream unknown-revocation
test name contradicted its success-only body; it now checks rejection with no CRL.
Filesystem CRL download/refresh, EventAdmin delivery and SCR/factory assembly remain
explicitly deferred, not represented as integration coverage by mocked registration.

Eight positive TLS cases failed before repair because Paho 1.2.5 replaced the Kura
factory's hostname policy with its default HTTPS check. A separate production commit
disables that override only for SSLSocketFactoryWrapper; its own socket policy remains
active. Enabled hostname verification still rejects a mismatch, and an added custom
factory case confirms Paho's default verification remains enabled for other factories.
The handwritten manifest adds only the required core.ssl package import.

All 18 MQTT cases and 48 Cloud Base cases pass with zero failures/errors/skips on
Maven 3.10.0/JDK 21; isolated installation succeeds. Remaining legacy cloud harness,
DataService/CloudService end-to-end assembly and IDEA/Equinox acceptance stay open.
