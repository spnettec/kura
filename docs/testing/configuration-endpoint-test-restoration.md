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

An isolated macOS development assembly now also exercises the actual Jetty/Jersey
HTTPS endpoint with Basic authentication, SCR ConfigurationRestService,
ConfigurationService and CryptoService. A snapshot written through HTTPS is
encrypted on disk and readable after a second Java process starts with the same
external master key and profile. Both HTTPS reads returned 200 with the real
HttpService PID; the encrypted file hash stayed the same across the restart.
See `configuration-rest-https-restart-validation-20261010.json`. This run used
the Mac development assembly from CLI; the exact HTTPS flow was not launched
from IDEA, and installed Debian package behavior remains outside this evidence.
No production code or handwritten OSGi metadata changed.

Validation: Failsafe verify selected ConfigurationEndpointsIT in migration-m2.
All upstream test method names match the restored parameterized method set; each
method executes once for HTTP and once for MQTT. See the module README for setup.
