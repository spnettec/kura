# System and tamper endpoint restoration

Two upstream source entries are restored in `kura-endpoint-tests` with Jupiter and
Failsafe over actual HTTP and MQTT, using the shared endpoint transport stack.

- Tamper: all eight upstream scenarios, each on both transports, plus an additional
  unbinding case on both: 18 passing invocations. They cover empty/multiple service
  lists, display/PID mapping, missing PID 404, tamper status/properties/timestamp,
  state-changing reset, `service.pid` fallback and removal after service unbinding.
  HTTP uses TamperDetectionRestService; MQTT uses TamperDetectionRequestHandler.
  Provider objects/state are controlled and bound explicitly to both implementations.
- System: all twelve upstream scenarios, each on both transports: 24 passing
  invocations. They cover framework/extended/Kura properties, GET and POST filters,
  exact JSON and provider exceptions mapped to 500. The upstream extended-property
  failure test accidentally requested framework properties; its resource path is
  corrected so the extended exception branch is now exercised.

The existing SystemServiceMockDecorator and six JSON resources are exported in a
restricted `fixtures` test JAR from REST system provider; they are not duplicated or
counted as newly reviewed sources. Its five existing tests plus install pass.
Local APIs, constants, properties and response behavior remain unchanged.

Maven 3.10.0 / Temurin 21, isolated repository: targeted tamper 18 and system 24
runs pass with zero failures/errors/skips. Alongside the previous identity 50 run,
there are 92 validated endpoint invocations across those runs, not a claim of one
combined full workspace execution. Tests retain the bounded transport and cleanup
checks from the shared fixture.

Full deployed SCR/configuration discovery and actual IDEA execution remain open.
No production code, handwritten metadata, D-Bus, YOFC/PLC4X or OPC UA changed.
