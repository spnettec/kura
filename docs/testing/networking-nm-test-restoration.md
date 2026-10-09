# NetworkManager test restoration — 2026-10-09

Upstream snapshot: kura-networking 20da91a3c21532d0d0cfa9c796b79068c61d16b1.
This audit records successive batches restored beside org.eclipse.kura.nm.
The source-review inventory and real runtime acceptance are tracked separately.

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

At this batch boundary the NM connector still needed review; its continuation
appears below. This is not real system D-Bus, DS or IDEA acceptance.

## Settings converter continuation

The fully reviewed NMSettingsConverterTest adds 153 passing invocations for
IPv4/IPv6, WAN priority, Ethernet, Wi-Fi/WPA/802.1X, modem/PPP and VLAN conversion.
It uses the current dbus-java 5.2.0 Variant and numeric types, including actual
certificate encoding and encryption/decryption of the public test key fixture.
No host network services are invoked. The full current NM module passes 1,441
invocations, with zero failures/errors/skips under Maven 3.10.0 / JDK 21 / Jupiter.
Log: /tmp/kura-networking-nm-settings-full.log.

Upstream fixtures are corrected so invalid inner authentication is tested with a
valid EAP method, negative WAN priority is actually tested in WAN mode, and null
Wi-Fi passwords are tested with a valid radio mode. IPv4/IPv6 status constants and
Ethernet property prefixes use the intended interface/family. These changes avoid
passing for an unrelated invalid input. Production behavior, dependency versions
and handwritten metadata are unchanged.

YOFC's upgraded networking implementation remains authoritative. Connector tests
must be checked against its D-Bus 5.2.0 API and virtual-thread lifecycle; upstream
Reapply assumptions must not be imported into the current update/activate path.

## D-Bus connector continuation

All 53 upstream scenarios were reviewed against the fork's current connector,
wrappers, signal locks and dbus-java core/transport 5.2.0 dependencies. 49 applicable
scenarios pass. The full NM module passes 1,490 invocations with zero failures,
errors or skips under Maven 3.10.0 / JDK 21 / Jupiter. Log:
/tmp/kura-networking-nm-connector-full.log.

The local connection path uses Update plus ActivateConnection. It deliberately
does not use upstream UpdateUnsaved/Reapply. Connection identities, object paths,
version-property bus names, IPv6 constants and Ethernet fixture keys were corrected
to exercise that local path. Activation assertions match the actual target device.
These four upstream-only scenarios are excluded, not passing/skipped cases:

- activateShouldNotBeCalledWhenReapplySucceeds
- applyShouldWorkWithEnabledModemWhenReapplySucceeds
- configurationEnforcementShouldUseReapplyWithExternalChangeSignal
- shouldStartModemTaskHandlerEvenIfReapplyFails

A mocked bus records real signal-handler registration and routes real D-Bus 5.2.0
StateChanged, DeviceAdded and ScanDone objects. Actual device/wireless locks and
connector/wrapper logic run. VLAN creation now asserts activation, replacing an
upstream unattached lock mock that could pass without creating the device. The
modem manager remains real; its scheduler construction is isolated because retry
scheduling has separate restored coverage.

Each case owns a fresh connector created through its constructor, preserving the
process singleton and avoiding system-bus access. The asynchronous case uses the
actual connector executor, waits for its CompletableFuture and asserts a virtual
activation thread. Teardown terminates the owned executor, stops modem handlers
and closes the scheduler construction mock. The old fixed twenty-second sleep is
removed. Production source and handwritten OSGi metadata are unchanged.

All NM source entries have now been reviewed; real system-bus/transport behavior,
monitor-thread races, full DS and IDEA acceptance remain open. Networking has four
REST sources left in the inventory, and the wider restoration is unfinished.

## Separate production repair: failed-operation state listeners

Five added regression cases reproduced leaked NMDeviceStateChangeHandler instances
when Update, AddConnection, ActivateConnection (physical or VLAN) or Disconnect
threw before waitForSignal(). On the unmodified production source all five fail
with one registered waiter remaining; none fail from a fixture error.

DeviceStateLock now has idempotent close(), and the connector scopes each state
waiter around the D-Bus operation as well as the subsequent wait. Existing signal,
timeout and interruption cleanup remains. Update/ActivateConnection selection,
modem monitoring, carrier-error handling and handwritten metadata are retained.
The fake bus also rejects duplicate removal, checking the successful path when
both waitForSignal() and try-with-resources close the waiter.

After the separate production repair all 54 connector cases and all 1,495 NM
module invocations pass with zero failures/errors/skips (Maven 3.10.0 / JDK 21 /
Jupiter). Logs: /tmp/kura-networking-nm-lock-negative.log and
/tmp/kura-networking-nm-lock-fixed-full.log. This repair concerns temporary state
listeners; it does not claim complete real-bus lifecycle acceptance.

The repaired NM bundle also packages and installs successfully into the isolated
migration-m2 cache (/tmp/kura-networking-nm-lock-install.log). Follow-up lifecycle
acceptance still needs to exercise failures before waiting in DeviceCreationLock
and WPAScanLock, in addition to the completed state-listener regressions.
