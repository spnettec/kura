# Configuration endpoint restoration

All 102 upstream ConfigurationRestServiceTest scenarios are retained and run over
both actual HTTP and MQTT transports: 204 passing invocations, zero failures,
errors or skips, Maven 3.10.0 / Temurin 21 / JUnit Jupiter.

The tests cover configuration/property projection, scalar and array metadata,
password encryption at the service boundary, updates, snapshots/rollback, factory
creation/deletion, validation and error mapping. The upstream ConfigurationUtil
helper is retained with the local getLocalizedDefinition contract. Both update
ConfigurationService overloads capture the property map passed by the actual
endpoint. Controlled CryptoService encryption produces a distinct value, allowing
assertions to detect a missing encryption call.

The shared fixture supplies actual Jetty/Jersey authentication and MQTT cloud
request processing, private H2 storage, a loopback broker and bounded cleanup.
ConfigurationService and CryptoService are controlled service boundaries; these
204 endpoint results alone do not claim persistent CM, SCR activation or runtime
master-key coverage. A companion cloud runtime scenario now crosses an authenticated
MQTT request into the actual SCR ConfigurationRestService and ConfigurationService:
CONF-V2 writes an encrypted snapshot file with the real CryptoService and reads it
back in the same Equinox process. Maven passed 13/13 cloud runtime tests, and Mac
IDEA directly passed the expanded method (1/1, exit code 0). See
`configuration-rest-mqtt-validation-20261010.json`.

Authenticated HTTP to the same SCR backend and encrypted snapshot/master-key
recovery after a new Equinox process remain to be verified. No production code,
OSGi metadata, network API, YOFC/PLC4X or official OPC UA behavior changes.

Validation: Failsafe verify selected ConfigurationEndpointsIT in migration-m2.
All upstream test method names match the restored parameterized method set; each
method executes once for HTTP and once for MQTT. See the module README for setup.
