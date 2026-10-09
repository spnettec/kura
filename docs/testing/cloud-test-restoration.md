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
