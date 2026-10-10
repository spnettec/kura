# Configuration runtime test restoration

All 46 upstream ConfigurationServiceTest scenarios execute through a JUnit Jupiter
parameterized controller, plus one fork plaintext/CDATA case: **47 passed**, no
failures/errors/skips. The root `-Posgi-it -pl :kura-osgi-tests -am verify` entry
built all 17 selected modules successfully; together with the existing six bundle
tests, the container module passed **53 tests**.

## Actual runtime boundary

The controller contains no business Kura JARs and asserts that ConfigurationService
cannot be loaded on its classpath. It installs 55 real bundles into a separate
Equinox per scenario, resolves their imports and uses actual SCR, ConfigAdmin,
MetaTypeService, configuration audit facade/implementation, XML marshalling and
CryptoService. The upstream scenario bodies and both component helpers live in a
separate opt-in fixture bundle with handwritten manifest/DS/metatype descriptors.
JUnit 5 assertions in that bundle use its actual imported Jupiter API bundle.
No Kura system export, wildcard import or shared business classloader is introduced.

Only SystemService's per-test directories, snapshot count and encryption setting
are controlled. Configurations, encrypted snapshots, passwords and plain XML pass
through real production services. The added case verifies the existing
`kura.snapshots.encrypt=false` switch, literal CDATA and XML round trip. Existing
snapshot permission and malformed-file retention regression tests remain in core.
Fixture services and bundle-loaded constructor dependencies are released; the
existing EquinoxExtension stops the framework and cleans successful test storage.
Failures retain live SCR/bundle diagnostics before the system proxy is removed.

The test-only factory metadata replaces the old DataService factory dependency.
It does not add cloud implementation packages to core. Both normal and self-
configuring helpers are actual SCR services; factory scenarios use actual CM/SCR
instances. Factories that are intentionally unknown to the runtime remain so.
Full deployed assembly, host SystemService, hardware and IDEA execution remain open.

## Adaptations and defects exposed

- Retain the local null-factory error wrapper (`KuraException` with the original
  `IllegalArgumentException` cause), rather than requiring the upstream exception
  to escape the fork's existing wrapper.
- Add the self-component's `kura.service.pid` to fixture DS metadata; the legacy
  test added this property through duplicate manual service registration.
- Wait for actual factory services and asynchronous rollback registration with
  bounded deadlines. Creating CM state alone is not counted as SCR activation.
- Use a value within the metadata range for the untouched-password update case;
  upstream used 42 with a declared maximum of 20.
- Correct the old rollback-by-ID case to create a target and a subsequent snapshot,
  invoke rollback(id), and inspect the restored properties. The original swallowed
  a missing-snapshot error and mutated its snapshot set during assertions.
- Fail immediately on precondition/assertion retrieval errors; require the expected
  PID and every property in snapshots. Unknown bulk-update PIDs are explicitly
  asserted absent instead of swallowing their null lookup. Snapshot equality checks
  properties, not only PID membership. All upstream scenario method names remain.

Default retrieval defects were repaired separately in `a17a9e7edc`; rollback
registration defects in `6596fa722a`. Each has negative-before/positive-after unit
regressions and its own audit. Those production repairs are separate from this
fixture commit and do not change handwritten production metadata or fork policies.

## Reproduction

Use Maven 3.10.0, Temurin 21 and one consistent Maven repository:

```sh
mvn -Posgi-it -pl :kura-osgi-tests -am verify
```

The osgi-it profile adds the fixture module before its controller dependency.
`target/it-bundles` retains the original JWT/fragment fixture set; additional
configuration bundles are copied into `target/config-it-bundles`. Ordinary
`mvn test` and distribution reactors do not install these test fixtures into Kura.
