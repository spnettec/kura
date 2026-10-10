# Camel upstream test restoration

2026-10-09; upstream snapshot `kura-camel@b51b9dd0`, all 14 inventory sources
reviewed against the current fork, which retains Camel 4.20.0. Twelve Jupiter
suites and two helpers now live under the production bundle's `src/test`.
Production sources, dependency scopes for production, and handwritten OSGi
metadata are unchanged.

## Fork acceptance scope (2026-10-11)

Camel upstream is a reference for retained assertions. Current fork behavior is
authoritative: Camel 4.20.0, Groovy/JavaScript init scripts with injected
camelContext/logger/webClient/vertx/rebind, file-backed scripts and hot rebind on
the same context, plus the modified management console ACE editors. XML editor
mode follows file.extension; initCode editor mode follows scriptEngineName.
An ordinary direct-to-log route does not cover these paths. Runtime acceptance
must include actual script execution, Vertx HTTP calls, file/inline updates,
context lifecycle and the production cloud transport. Browser editor/save
acceptance is separate from a ConfigurationService API update.

The opt-in `kura-camel/acceptance/full-runtime-fork-probe` helper exercises these
runtime paths without entering the default reactor or production packages.
Its build/run alone does not count as a successful result; accepted evidence
is now linked in `mac-complete-camel-fork-validation-20261011.json`: nine actual
MQTT deliveries and four Vertx HTTP calls passed with Groovy file/inline updates
and context lifecycle. JavaScript init execution and browser editor/save remain
explicitly unverified. No upstream router, dependency downgrade or
replacement of the fork script/editor behavior is proposed.

| Suites | Passing cases |
| --- | ---: |
| DependencyRunner / Configuration / PayloadFactory | 14 |
| KuraServiceFactory / KuraCloudComponentResolver | 7 |
| DefaultCamelCloudService / CamelCloudClient | 9 |
| KuraCloudComponent / KuraCloudProducer | 13 |
| Router / Payload / TypeConverter | 9 |
| Total | 52 |

The XML fixture runs the real AbstractXmlCamelComponent, CamelRunner, XML DSL
loader, route controller and DefaultCamelContext. Only OSGi bean/service lookup
is replaced by an in-process registry; Camel resolves languages/components from
the test classpath. The tests exercise actual message routing and type-converter
registration. Activation must produce a started context, and teardown deactivates
the component. ProducerTemplate instances are closed.

Local XML changes recreate the context. Payload expectations are therefore set
on the new context, avoiding the upstream fixture's stale mock endpoints. Route
updates additionally assert unchanged XML retains the context, changed XML stops
the old context, and a replacement with the same route ID has the new output URI.

Other corrections to upstream test fixtures:

- The dependency rebind test lacked `@Test`; it now executes.
- A null producer payload must actually throw, rather than passing if a catch
  block is never entered.
- Mock executor submissions run a FutureTask and assert completion or its captured
  exception, matching ExecutorService.submit semantics instead of throwing task
  failures synchronously. No real subscription executor is started by these tests.
- Configuration wrapper constructors use valueOf with unchanged assertions.

The test classpath supplies the APIs normally wired by OSGi: activation 2.1.2,
Groovy 5.0.5, Jackson core 3.2.0 and Jakarta JMS 3.1.0, plus Log4j API,
kura-test-support and Camel mock 4.20.0. Groovy/Jackson/JMS versions match the
current target platform. These test-only dependencies let Camel's normal converter
loaders initialize without changing deployed bundle contents or downgrading Camel.

Validation: Maven 3.10.0, Temurin JDK 21, Jupiter, isolated migration-m2 cache:

```sh
mvn -f bundles/org.eclipse.kura.camel/pom.xml \
  -Dmaven.repo.local=/Users/heyoulin/iot-kura-develop/migration-m2 test
```

52 tests, zero failures/errors/skips. Direct macOS IDEA JUnit class Run then
passed RouterTest 5/5, PayloadTest 1/1 and TypeConverterTest 3/3 using Maven
3.10.0, JDK 21 and the isolated migration cache. In the separate isolated Mac
Equinox/SCR development assembly, all three Camel bundles were ACTIVE. Camel's
validation service and cloud service factory were ACTIVE, and the cloud
component resolver was SATISFIED. Creating a temporary XML router through the
configuration REST factory endpoint activated its DS instance, registered a
CamelContext and started a local direct-to-log route. Deleting the configuration
stopped the route and unregistered the context; SCR returned to zero router
instances. See `mac-camel-idea-scr-validation-20261010.json`. Installed Debian
sibling package and external cloud transport acceptance remain separate.
