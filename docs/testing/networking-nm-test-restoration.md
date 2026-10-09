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
