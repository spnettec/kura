# Add-on archetype migration — 2026-10-10

The generated add-on now uses `kura-build-parent`, Maven Bundle Plugin 6.0.0,
JDK 21 and JUnit 5. The template no longer creates a Tycho target definition,
PDE test bundle or a copied test environment. Its example production Java and
handwritten bundle Manifest remain unchanged.

## Result and boundaries

- The generated root builds the bundle, ordinary tests, real Equinox integration
  test and existing Debian distribution with `mvn verify`.
- The existing component/metatype annotations explicitly generate two DS XML files
  and one metatype XML file. Handwritten import ranges, lazy activation, singleton
  identity, Service-Component wildcard and Java 21 capability are preserved.
  Automatic package export is disabled; no new exported package is introduced.
- The ordinary test retains its options assertion. The integration test uses actual
  bundle classloaders, SCR and ConfigAdmin. It checks that the configuration-required
  component is absent before configuration, then registers with the configured
  property and uses the actual Kura API package provider. Kura implementation JARs
  needed for class resolution are installed but not activated as host services.
- The bundle source JAR contains all six example Java files. The Debian payload
  keeps the existing `plugins/6s` layout and contains the exact newly built bundle.
  Signing remains opt-in. The generated README documents the matching installed
  Kura artifacts, Git version prerequisite and IDEA working directory.
- Removed template files were only consumed by the former target/PDE test setup.
  General repository `.target`, `.launch`, Eclipse workspaces and installations
  were not removed in this batch. P7 CI and broader cleanup are still pending.

## macOS validation

Maven 3.10.0 and JDK 21 installed the archetype, then generated a fresh independent
project with group `org.example`, artifact `kura-addon-acceptance`, package
`org.example.addon`, and Kura version `6.0.0-SNAPSHOT`. The generated fixture was
initialized as a temporary Git repository for the existing distribution versioning.
Both initial and consecutive incremental `mvn verify` passed: **one ordinary test
and one real Equinox test**, zero failures/errors/skips per build. Incremental
packaging retained the three descriptors without duplication.

An earlier draft needed the SLF4J ServiceLoader capability providers in its runtime
collection. The final fixture includes those real bundles; no business packages
were added to the framework system package list. A draft assertion attempted a
method absent from the registered marker interface and was replaced with the
ConfigAdmin registration-property assertion described above. Failed drafts are
not counted as passing.

The final artifact audit verifies the handwritten headers, absence of implicit
exports, class major 65, descriptor count, source bytes and Debian bundle bytes.
See [machine-readable result](addon-archetype-validation-20261010.json).
Logs, reports and artifacts are archived locally at:

```
/Users/heyoulin/iot-kura-develop/migration-baseline/addon-archetype-20261010/
```

The test project is `/tmp/kura-addon-mbp-final-20261010/kura-addon-acceptance`.
This is Maven/runtime evidence; a new generated-project IDEA GUI session was not
performed. No additional Linux validation was run, following the user's scope.
