# Legacy build configuration consumer audit — 2026-10-10

The default Maven/IDEA path is independent of Tycho. A static traversal of the root
POM, every declared profile module, and the core distribution now visits **192
POMs** without Tycho plugin configuration or `eclipse-*` packaging. This checks the
reachable configuration graph, not every legacy POM that could be invoked directly.
See [the exact paths and consumers](legacy-config-consumer-audit-20261010.json).

The audit found an empty `kura-artemis/tests` aggregator still included by its root.
It declared old JUnit 4/Mockito dependencies, Tycho pluginManagement and copied test
environment files but contained no Java test source or child modules. There were
no other consumers of its artifact. Removing that module and its six tracked
configuration/environment files passed Maven 3.10/JDK 21 `validate` for all seven
remaining Artemis modules. No applicable test source or production bundle changed.
The log is `/tmp/kura-artemis-legacy-cleanup-validate.log`.

The following files are intentionally retained after checking actual consumers:

| Retained configuration | Consumer/reason |
| --- | --- |
| `kura/kura-pde-deps` and `target-platform/target-platform-pde-deps` | Maven-location entries in 11 sibling `.target` files still reference these artifacts. |
| Core and sibling `.target` files / PDE project metadata | Existing Eclipse compatibility workspace remains; it is not used by the default Maven/IDEA entry. |
| `target-platform` P2 producer POMs and installer | Legacy PDE/external artifact compatibility; the 14 default Maven wrappers are not assumed to cover every historical P2 output. |
| Emulator `src/main/resources/*.launch` | Four tracked launch resources are packaged by the ordinary Maven resources configuration; their current JAR bytes match source. Removing them would change bundle resources. |
| `kura/setups` launchers/formatters and Oomph setup | The setup still references its launchers. Existing Eclipse installation/workspace is retained as previously requested. |
| Bundle `build.properties` | Legacy PDE packaging/import metadata and migration baseline capture; no blanket filename deletion is performed. |

Archetype-only target/PDE test files and obsolete Travis configuration were removed
in the earlier scoped batches. README and AGENTS now describe the actual Maven
Bundle Plugin/JDK 21 build, independent PLC4X prerequisite, current test report
locations, IDEA profiles, Failsafe skip flag and ARM64/AMD64 image path. Business,
OSGi metadata, i18n, deleted-feature and networking/D-Bus boundaries are unchanged.

This completes this consumer-audit pass, not a claim that all legacy compatibility
assets can be deleted. Removing the retained Eclipse/P2 surface would require its
consumers to be retired or migrated first. Deferred runtime scenarios in the test
inventory also remain separate from this build cleanup. No additional Linux
validation, application rebuild or personal-data change was performed.
