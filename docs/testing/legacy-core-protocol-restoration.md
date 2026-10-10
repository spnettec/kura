# Legacy core configuration and inventory scenarios

The last six core-suite sources at upstream `e500a68d` have been reviewed. Eight
scenarios now run with JUnit 5 in isolated Equinox frameworks, using the existing
test-only bundle. This closes the source-disposition queue; it does not close
runtime, transport, platform or IDEA acceptance.

## Configuration: four scenarios

`LegacyCoreScenarios` retains the four upstream method names. The real
ConfigurationService, ConfigAdmin, SCR, metatype, CryptoService and XML services
provide the behavior. A new SCR fixture component uses the original 18 attribute
definitions, receives actual activation/update callbacks and exposes their values.

- Service presence checks the implementation bundle.
- Local updates check all nine scalar types and all nine array types, update
  callbacks, validation failures and rollback to the original snapshot.
- CONF-V1 GET / snapshot / PUT / GET / rollback checks real XML, response codes,
  asynchronous updates and final values through the registered production handler.
- Snapshot retention creates twice the configured maximum and checks the limit.

The current API merges updates with running properties. Omitting a required
attribute therefore retains its old value; explicitly setting it to null is
rejected. Invalid types and missing required values are reported inside
KuraPartialSuccessException. The migrated test checks the exact underlying error
codes. The old `assertFalse(..., false)` assertions could pass when no exception
was thrown and are not retained. No production behavior was changed for these
expectations.

## Inventory: four scenarios

`LegacyInventoryScenarios` retains testGetPackages, testGetBundles,
testGetInventory and testGetSystemPackages. Felix DeploymentAdmin installs a
manifest-only test bundle from an in-memory deployment package in each disposable
framework. The actual SCR InventoryHandlerV1 and JSON service query that installed
package/bundle. Assertions parse JSON and verify names, versions, real bundle ID,
ACTIVE state, unsigned status and resource types. Cleanup uninstalls the package
and checks UNINSTALLED state.

This generated package replaces the old precompiled HelloWorld fixture; it has no
application activator. SystemService supplies one deterministic DEB entry. Actual
Linux package-manager execution remains separate platform validation.

## Support-source dispositions

| Upstream source | Current implementation / disposition |
| --- | --- |
| IConfigurationServiceTest | Empty marker replaced by the explicit SCR LegacyConfigurationComponent service and its original metatype/PID. |
| CoreTestXmlUtil | Its live snapshot-ID consumer is retained as namespace-aware, external-entity-disabled DOM parsing in LegacyCoreScenarios. Configuration bodies use the real XML service; current inventory responses use JSON. Unused historical inventory XML parsers are not copied. |
| CloudEndpointPublisher | Replaced by the existing lifecycle-managed endpoint MqttTransport for actual MQTT request/reply, and by an explicitly scoped RequestHandlerRegistry fixture for these real-container scenarios. No duplicate listener-owning global helper is added. |
| RequestIdGenerator | Existing MqttTransport uses a fresh UUID for each actual MQTT request and an independent observer ID; no timestamp/random singleton is needed in the direct registry fixture. |

The four support files contain no independently counted test cases.

## Boundaries and validation

The new protocol scenarios call handlers obtained through an actual SCR binding
to a controlled RequestHandlerRegistry. They do **not** traverse MQTT. The
previously passing HTTP/MQTT endpoint suites exercise transport with controlled
backend services; these are distinct layers, not a claim of combined end-to-end
coverage. Full MQTT plus these real OSGi backends remains an acceptance item.

Controller classpaths contain no Kura business JARs. The fixture uses explicit
package imports and checks actual package providers. No Kura packages are exported
from the system bundle and no wildcard imports or shared business classloader are
introduced. System paths, management ignore list and OS package enumeration are
controlled inputs. Production and existing handwritten metadata are unchanged.

Maven 3.10.0 / Temurin 21 validation: the 20-module root reactor passed all eight
new container scenarios and selected dependency unit tests. The full container
suite then passed **62 tests with zero failures/errors/skips** after extending the
shared test bundle. Its snapshot comparator now compares array contents; the new
18-attribute fixture exposed the old reference-equality assertion. IDEA GUI, full deployed
assembly and Linux/runtime acceptance remain open.
