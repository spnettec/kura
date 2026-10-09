# NetworkManager test restoration — 2026-10-09

Upstream snapshot: kura-networking 20da91a3c21532d0d0cfa9c796b79068c61d16b1.
This audit covers ten suites restored beside org.eclipse.kura.nm. Remaining NM
sources are still unreviewed in the authoritative inventory.

| Suite | Passing invocations |
| --- | ---: |
| ModemTaskManager | 6 |
| ModemTaskScheduler | 11 |
| WpaSupplicantDbusWrapper | 4 |
| MMPositionProvider | 3 |
| DhcpServerMonitor | 2 |
| DnsServerMonitor | 7 |
| DhcpServerConfigWriter | 5 |
| FirewallNatConfigWriter | 4 |
| NMModemTaskHandler | 3 |
| WpaScanDoneHandler | 2 |

Maven 3.10.0, JDK 21 and JUnit Jupiter: 47 new invocations pass; the full current
module passes 1,035 including 988 previously restored invocations. Zero failures,
errors or skips. Logs: /tmp/kura-networking-nm-lifecycle.log and
/tmp/kura-networking-nm-lifecycle-full.log.

- ScheduledTasks advances requested deadlines and executes the actual component
  callbacks, retaining modem retry/reset, cancellation and monitor assertions.
  Factory interception is scoped to component construction/startup so Jupiter's
  own ten-second timeout executor is unaffected. Each case stops its component,
  clears the pending callbacks and closes static mocks. This tests scheduling
  behavior deterministically, not real thread races or executor timing.
- NMDbusConnector and LinuxDns singleton access is intercepted before component
  creation. D-Bus devices, commands and DNS services are doubles; no connection to
  the host's system bus or network services is made. WpaSupplicant's real bounded
  synchronous wait is retained at one second.
- DNS stop now starts and then stops the monitor, instead of only stopping an
  object with no worker. The actual DNS reconfiguration delay remains bounded.
- DHCP config and lease files use per-test temporary directories. NAT tests close
  a scoped LinuxFirewall factory mock instead of replacing its static singleton.
- Position tests use the actual NMEA resources/parser and callback, with simulated
  three-second refresh intervals, and stop an existing refresh task on teardown.
- DnsServerService follows this fork's public API package. Guava and Log4j API are
  test-only classpath dependencies. Production code, manifest and DS metadata are
  unchanged; no real D-Bus/Linux/OSGi/IDEA acceptance is claimed.

## Status and configuration continuation

Four more suites pass 253 invocations: signal conversion 202, status conversion 20,
status service 14 and configuration service 17. The full NM module now passes
1,288 invocations with no failures/errors/skips. Log:
/tmp/kura-networking-nm-status-config-full.log.

- Signal conversion retains all 202 upstream input/expected pairs in Jupiter
  method sources; expected values are not computed from production formulas.
- Status tests retain IPv4/IPv6, VLAN, modem, SIM, bearer-byte and D-Bus exception
  assertions. A fixture typo setting signal quality twice now supplies quality
  100 and strength -53 separately, with explicit checks for both.
- Configuration service tests mock only the monitor and NAT-writer construction
  boundaries, plus existing D-Bus/command/keystore services. Real activation,
  update, metadata, PPP-name migration, DHCP eligibility and certificate lookup
  logic runs; the separately restored writer/monitor suites cover those doubles.
  Teardown deactivates the service and closes all construction mocks.
- The update scenario now calls update() after activation and clears its recorded
  event first. The upstream scenario accidentally called activate() twice instead.
  Local event delivery is synchronous, so the old six-second sleep is unnecessary.
- Local metadata has 155 attributes for this fixture; the upstream additional
  802.1X password attribute remains absent. PPP interface-list assertions compare
  membership instead of depending on HashSet iteration order. Enterprise Wi-Fi
  checks the certificate/private-key objects actually placed in the event.
- NMSettingsComparatorTest (24 cases) and ModemManagerDbusWrapperTest (22 cases)
  are not applicable to the current API. Their required comparator and
  setModemModes API are absent in the current source, confirmed by graph and
  source searches. They are recorded as exclusions, not passing/skipped suites;
  neither new production feature is imported.

The NM connector and settings-converter sources still need review. This is not
real system D-Bus, monitor-thread concurrency, DS or IDEA acceptance.
