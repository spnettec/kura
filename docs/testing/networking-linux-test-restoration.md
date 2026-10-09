# Linux network test restoration — 2026-10-09

The 21 sources in upstream `kura-networking` revision
`20da91a3c21532d0d0cfa9c796b79068c61d16b1`, module
`org.eclipse.kura.linux.net.test`, are reviewed: 19 suites and two fixtures.
They now live beside the implementation in
`kura-networking/bundles/org.eclipse.kura.linux.net/src/test`.

Maven 3.10.0 / JDK 21 / JUnit Jupiter executed 137 passing invocations, including
132 from the adapted upstream suites and five separate production regressions.
There are zero failures, errors or skips. After the module run, the two Wi-Fi
capability cases were strengthened and passed again individually. These checks
exercise Java behavior; they do not establish real Linux kernel, hardware,
NetworkManager/D-Bus, OSGi DS, or IDEA acceptance.

## Isolation and substantive assertion repairs

- DNS, DHCP leases, dnsmasq config, firewall files and the IP forwarding file use
  per-test Jupiter temporary directories. CommandExecutorService is mocked.
  No test executes the host's iptables, ip6tables, iw, dnsmasq or systemctl.
- The systemd availability cases execute an owned temporary shell script returning
  status 0 or 4. This makes the previously ignored success case runnable, with a
  ten-second bound. It does not contact systemd.
- LinuxFirewall tests construct a fresh instance through its private constructor
  with the constructor's IptablesConfig boundary mocked, then attach a real
  serializer with temporary paths. They avoid the process-wide singleton and
  preserve the production first-boot SSH/HTTPS safety-rule implementation.
- PPP tests retain the real signal escalation path and have a 15-second bound.
  File construction around disconnect is intercepted after class initialization,
  so probing/removing `/var/lock` is isolated as well as process signaling.
- DHCP manager tests restore the static selected tool after each case. Static
  mocks close after use; helper command output no longer swallows write failures.
- IPv4 and IPv6 assertions read the final file produced by saveKuraChains(), which
  moves its temporary file. Remove upstream branches that swallowed IO errors,
  skipped assertions when files were missing, or fabricated IPv6 output from the
  expected rules. Required output must now exist and contain the real rules.
- Wi-Fi capability assertions check the requested expected capabilities, including
  distinct WEP40 and WEP104 values. The upstream self-membership assertion could
  pass with an empty result. A NAT deletion assertion now checks the manual NAT
  set it actually modified, rather than the automatic NAT set.

## Local behavior retained

- IPv4 still emits its two explicit echo request/reply DROP rules when ICMP is
  disabled. IPv6 retains its current policy and unrestricted discovery rules.
- Additional firewall rules preserve the independently selected ICMP flag; both
  true and false are tested. Do not import upstream implicit ICMP flag changes.
- The local legacy unblockAllPorts() resets rules; it does not throw the newer
  upstream UnsupportedOperationException. The test records the actual local
  behavior without making a claim about kernel-wide unblocking.
- Individual rule commands and chain-existence checks remain in place. Do not
  import upstream batched restore behavior or its command-line flags.
- The single upstream bulk-replace scenario is excluded because the local
  AbstractLinuxFirewall has no replace(List,List,List) API. It is recorded in that
  source's inventory entry; no production API was added to satisfy the test.

## Independently committed production defects

- Networking `8881abc`: save/restore now select iptables or ip6tables from the
  configuration's address family. Before the fix, the two IPv6 assertions failed
  while the IPv4 cases passed; all four pass after the two-line correction.
- Networking `2095388`: blockAllPorts() also removes manual NAT rules. Its focused
  regression failed before the missing deleteAllNatRules() call and passed after.
  The shared reset path also applies this correction to legacy unblockAllPorts().

Negative validation: five tests, three failures, zero errors. Fixed validation:
five tests, zero failures/errors/skips. Test-only dependencies do not alter the
handwritten manifest or DS metadata.

The module was then packaged and installed into the dedicated migration Maven
repository with tests skipped because the execution checks above had passed.
Validation logs for this session are `/tmp/kura-firewall-regressions-negative.log`,
`/tmp/kura-firewall-regressions-fixed.log`, `/tmp/kura-networking-linux.log`,
`/tmp/kura-networking-linux-capabilities.log`, and
`/tmp/kura-networking-linux-install.log`.
