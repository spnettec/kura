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
