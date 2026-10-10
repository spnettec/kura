# Wires and networking transport continuation — 2026-10-10

The existing sibling component scenario suites now also execute through the real
HTTP/Jersey/authentication stack and local MQTT broker/request transport. Their
assertions are inherited from published `fixtures` test JARs; scenarios are not
copied into a second implementation. Fresh per-method instances prevent shared
Mockito state from leaking between inherited tests.

| Suite | HTTP | MQTT | Total |
| --- | ---: | ---: | ---: |
| WireGraphEndpointsIT | 49 | 49 | 98 |
| NetworkConfigurationEndpointsIT | 16 | Not provided by this endpoint | 16 |
| NetworkStatusEndpointsIT | 35 | 35 | 70 |
| **Total** | **100** | **84** | **184** |

All final results have zero failures/errors/skips on macOS, Maven 3.10.0, JDK 21
and JUnit 5. Wires fixture commit is `4774dd5`; networking fixture commit is
`fb4679d`. Their original 49 and 47 component tests were also verified before
publishing the fixture JARs.

Configuration covers the original 12 component scenarios, the original request
without credentials (401), incorrect credentials (401), an authenticated identity
without the endpoint permission (403), and a non-administrator with
`rest.network.configuration` (200). No MQTT configuration API was invented.
Status preserves the local IPv4/IPv6, Ethernet, Wi-Fi, modem, bearer and SIM DTOs.
The existing YOFC/dbus-java interfaces and Update/Activate behavior are unchanged.

The Wires fixture uses a 64 KiB local broker message limit. Two driver-descriptor
responses exceeded Moquette's default 8092 bytes after MQTT JSON/base64 framing;
the first 98-case run reported two timeouts. No assertion or request timeout was
relaxed. Both cases subsequently passed as part of the complete 49-case MQTT run.
The first combined run reported one network-configuration fixture error because
its HTTP DELETE method was also supplied as the MQTT method name. The adapter now
uses the transport's DEL alias. All 16 configuration tests were rerun successfully;
the already passing Wires and status suites were not repeated.

Configuration/network services and SCR boundaries remain controlled test fixtures.
The sockets, broker, request decoding, response mapping and HTTP authorization are
real. These results do not establish actual DS component creation/service arrival,
hardware, NetworkManager or system D-Bus behavior. No host network configuration
was changed and no additional Linux verification was run.

[Report checksums and source hashes](wire-network-endpoint-validation-20261010.json)
identify the exact final evidence. Initial and final reports/logs are retained at:

```
/Users/heyoulin/iot-kura-develop/migration-baseline/wire-network-endpoints-20261010/
```

Run the three suites after installing the corresponding current sibling fixtures:

```sh
mvn -f kura-endpoint-tests/pom.xml \
  -Dit.test=WireGraphEndpointsIT,NetworkConfigurationEndpointsIT,NetworkStatusEndpointsIT verify
```

Pass the same explicit Maven repository used for those installations. This is
additional scoped evidence after the archived 5,280-invocation workspace build;
that historical build count is unchanged. Inventory source dispositions also
remain unchanged; only the covered transport/authentication deferrals are removed.

An isolated Mac Equinox/SCR development assembly later returned HTTPS 200 for
`networkConfiguration/v1/configurableComponents` and its configurations list,
and 401 without authentication. This establishes actual DS registration and
ConfigurationService/CryptoService read-path wiring for the network-configuration
REST provider. The network-status routes returned 404 in this macOS runtime, so
their DS service-arrival boundary remains open. No network settings were changed
and no additional Linux, D-Bus or hardware validation was performed. Evidence:
`mac-deployment-network-rest-scr-validation-20261010.json`.

The complete `WireGraphEndpointsIT` class also passed direct Mac IDEA JUnit Run,
98/98 over HTTP and MQTT. This exercises the scoped wire helper mappings in the
IDEA module; deployed SCR service arrival and end-to-end event/wire routing remain
separate. See `mac-idea-rest-endpoints-validation-20261010.json`.

In the isolated Mac Equinox/SCR development assembly, the Wires core and REST
bundles were ACTIVE. `WireGraphService` and `WireRestService` each had an ACTIVE
DS instance; the graph service was bound to the real Equinox WireAdmin and core
ConfigurationService, and was used by the REST bundle. A certificate-validated
HTTPS GET of `/services/wire/v1/graph/snapshot` returned the empty graph with
status 200 for the isolated admin and 401 without authentication. See
`mac-wire-scr-service-validation-20261010.json`. Component/driver factory
instance arrival, WireAdmin route delivery and installed sibling package
acceptance remain open.
