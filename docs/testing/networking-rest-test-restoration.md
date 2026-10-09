# Networking REST source audit — 2026-10-09

Pinned upstream: kura-networking 20da91a3c21532d0d0cfa9c796b79068c61d16b1.
All four remaining REST source entries were read: two suites and two configuration
fixtures. They are restored beside the corresponding production bundles.

| Suite | Passing component scenarios | Runtime work still pending |
| --- | ---: | --- |
| NetworkConfigurationRestServiceTest | 12 of 13 original scenarios | The original unauthorized HTTP request; real HTTP and DS |
| NetworkStatusRestServiceImplTest | 35 distinct scenarios | Original HTTP/MQTT transport matrix; DS |

Maven 3.10.0, JDK 21 and JUnit Jupiter report zero failures/errors/skips in both
modules. Logs: /tmp/kura-networking-rest-configuration.log and
/tmp/kura-networking-rest-status.log. The unexecuted authorization/transport paths
are recorded as deferredValidation in the inventory, not passing or skipped tests.

The component tests run the actual endpoint methods, JaxRsRequestHandlerProxy,
request decoding, response encoding and DefaultExceptionHandler. Configuration,
network status and crypto services are boundary mocks with per-case state; no
static OSGi registrations, user accounts, host interfaces or external brokers are
created. Unknown-route KuraException uses the actual exception mapper.

- Configuration coverage retains PID filtering, current/default metadata, updates,
  net.interfaces merging, unsupported factory requests and empty factory metadata.
  The PID fixture now includes a non-network component and compares returned set
  membership, rather than HashSet iteration order. Empty and rejected factory
  responses also check status; the local rejected-factory status remains 500.
- The helper implements YOFC's getLocalizedDefinition(String) API. No metadata or
  localization implementation is replaced. Two upstream request literals now
  quote the properties key so they contain valid JSON.
- Status retains all 35 validation, error, IPv4/IPv6, loopback, Ethernet, Wi-Fi,
  channel/access-point, modem, bearer and SIM JSON scenarios. They run once through
  the in-process proxy, not twice with fake HTTP/MQTT transport labels.
- Jupiter, Mockito, Gson, Jersey runtime delegate and Log4j API are test-only
  dependencies. Log4j API is required by the fork's KuraException initialization;
  its initial missing-class error was a test classpath failure, not a production
  networking defect.

The original shouldReturnUnauthorizedStatusWhenNoRestPermissionIsGiven requires
HTTP authentication and is explicitly deferred. No fake 401 or annotation-only
substitute is counted as its restoration. The remaining runtime acceptance must
exercise the real authentication filter, HTTP/MQTT transports and DS bindings.
Production source and handwritten OSGi metadata are unchanged in this REST batch.
