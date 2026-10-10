# HTTP and MQTT endpoint integration tests

This opt-in module exercises the same endpoint scenarios over actual loopback HTTP
and MQTT. It is outside the core/sibling production reactors and has test-scoped
dependencies only. It does not add sibling implementation imports to core bundles.

Use Maven 3.10 and JDK 21. After installing the core and `kura-cloud` modules with
test compilation enabled into the same Maven repository, run:

```sh
mvn -f kura-endpoint-tests/pom.xml verify
```

For a complete workspace reactor, enable `workspace,endpoint-it` and select this
module with `-pl :kura-endpoint-tests -am verify`. The existing `RUN_IT=1
./build-all.sh` path also runs it after the sibling build. Failsafe runs `*IT` classes
at `verify`; `test` alone does not run the integration scenarios.

The module consumes the `fixtures` test JARs attached by REST provider and cloud base
provider. It does not register their source directories as duplicate IDEA source
roots. `maven.test.skip=true` does not build those artifacts; `RUN_IT=1` already enables
test compilation. No fixture artifact is included in a runtime distribution.

- HTTP uses the real RestService filters/resources, Jetty/Jersey, identity/password
  implementation and Felix roles through the shared REST fixture.
- MQTT uses an independent Paho observer, a private Moquette broker, actual Kura
  MqttDataTransport/DataService, H2 storage, Kapua CloudService request registry and
  MessageHandlerCallable, JAX-RS request proxy and real JSON payload codecs.
- The observer publishes unique request IDs and waits for matching replies. Connect,
  request and cleanup operations are bounded; listeners, observers, servers,
  executors and databases are released by their owning fixtures.
- MQTT control prefix `EDC` is used because Moquette 0.18 rejects client publications
  on `$` topics. The production default and protocol implementation are unchanged.
- V1 identity tests retain their controlled LegacyIdentityService boundary and
  verify create/update/delete calls. V2 tests use the actual identity service and
  password policy, including state checks after changes. Extension service binding
  is explicit and per test; local `getLocalizedDefinition` is preserved in fixtures.

OSGi registry/configuration boundaries are controlled and services are activated
explicitly. This tests real transport and component interaction; full SCR, persistent
configuration/keystore storage, deployed runtime and IDEA execution remain separate
acceptance work. The `kura-cloud` checkout and its matching installed artifacts are
required; YOFC/PLC4X and official OPC UA are not extended by this module.

System property and tamper detection scenarios also run over both transports.
System provider exports its existing mock decorator and JSON resources in a
`fixtures` test JAR; install it with test compilation enabled before this module.
See `docs/testing/system-tamper-endpoint-test-restoration.md` in the repository root.

Service-listing scenarios use a private real Equinox service registry. SCR description
and configuration-service boundaries are controlled; see the service-listing audit.
