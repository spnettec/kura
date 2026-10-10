# Identity HTTP and MQTT endpoint restoration

All nine upstream V1 and sixteen V2 endpoint scenarios are restored as Jupiter
parameterized tests, each executed over HTTP and MQTT: 18 + 32 = 50 passing
invocations, zero failures/errors/skips. The shared upstream MqttTransport helper
is restored with explicit ownership and bounded requests.

The opt-in `kura-endpoint-tests` module runs with Failsafe at `verify`, consuming
REST provider and cloud base `fixtures` test JARs. All dependencies are test scoped;
there are no duplicate external source roots or added sibling imports in core
production bundles. Cloud fixture export is committed in kura-cloud `50a3a68`.
Core REST provider has 119 passing tests plus installation; cloud base has 57.

The HTTP side uses actual Jetty/Jersey, RestService authentication, identity,
password and role implementations. V1 keeps the upstream LegacyIdentityService
mock boundary and additionally verifies create/update/delete calls. V2 uses the
real identity service and checks persisted fixture state after identity, permission,
password and extension changes. The local localized metadata API is retained.

The MQTT side traverses a private Moquette broker, real Kura MqttDataTransport,
DataService/H2, Kapua CloudService request registry/MessageHandlerCallable and
JAX-RS proxy, with real JSON codecs in both directions. A separate Paho client
correlates unique request IDs and reads response codes/body. `EDC` avoids Moquette
0.18 rejecting client publications on `$` topics; production defaults are unchanged.

Each case closes its observer, cloud registration/listeners and birth scheduler,
HTTP server/client, DataService/transport executors and database. SystemService
and SystemAdminService boundaries provide device name and string uptime needed
by the real disconnect payload. An intermediate fixture cleanup NPE was corrected;
only the final clean artifact-based run is reported as passing.

Validation used Maven 3.10.0 and Temurin 21 with an isolated Maven repository. A
clean build of this module compiled only its four source files, proving it consumed
the exported fixture JARs. `RUN_IT=1 ./build-all.sh` runs it after sibling installation;
root `endpoint-it` profile exposes it for IDEA/Maven import. See its README for
standalone commands and prerequisite artifacts.

Service activation/registry/configuration boundaries are explicit fixtures. Mac
IDEA class Run passed V1 18/18 and V2 32/32. In the isolated Mac Equinox/SCR
runtime, certificate-validated authenticated HTTPS passed 14/14 requests:
V1 and V2 identity creation, permission assignment, cross-version reads,
deletion, and final identity/permission cleanup. This validates the real
configuration-backed write path in the development assembly. See
`mac-idea-rest-endpoints-validation-20261010.json`,
`mac-rest-scr-endpoint-validation-20261010.json` and
`mac-identity-scr-mutation-validation-20261010.json`. Installed Debian package
acceptance remains separate. No production logic,
handwritten OSGi metadata, YOFC/PLC4X or official OPC UA behavior changed.
