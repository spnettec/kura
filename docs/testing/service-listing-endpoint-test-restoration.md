# Service listing endpoint restoration

All 28 upstream scenarios are restored with Jupiter in `kura-endpoint-tests`:
27 run over both HTTP and MQTT; the unauthenticated REST-only case runs once rather
than counting an MQTT invocation with no assertion. All 55 invocations pass.
The four original helper sources (two marker interfaces, TargetFilterTestService
and request/response constants) are reused, with no separate scenario count.

Each test starts a private Equinox registry. Actual service registration, objectClass,
LDAP filters, property presence/value/array matching, AND/OR/NOT and deregistration
are exercised by the production RestServiceListingProvider. HTTP uses actual
identity authentication; an authenticated identity without permissions can list
services, and an unauthenticated request receives 401. Factory PID/interface/property
and reference queries use explicit SCR descriptor/ConfigurationService boundaries
matching the three upstream fixture descriptors. Their deployed SCR/metatype
assembly is not claimed. JSON validation/error responses remain unchanged.

Every scenario closes its request transport, unregisters services and handler,
deactivates the fixture component and stops Equinox within five seconds; inherited
HTTP/MQTT/SQL cleanup remains active. Tests use strong fixture passwords without
changing production policy. Existing OSGi promise 1.3.0/function 1.2.0 are test-only
dependencies needed to load SCR's API; production bundle imports are unchanged.

Maven 3.10.0 / Temurin 21: a five-invocation fixture smoke check and the complete
55-invocation run pass, zero failures/errors/skips. The earlier classpath-incomplete
run was terminated and is not counted. Mac IDEA class Run also passed 55/55;
isolated Equinox/SCR HTTPS servicePids and factoryPids returned 42 and 67 PIDs.
Installed Debian SCR/metatype factory discovery and filtered queries under that
assembly remain open. See `mac-idea-rest-endpoints-validation-20261010.json` and
`mac-rest-scr-endpoint-validation-20261010.json`.
