# ${artifactId}

Build with Maven 3.10 and JDK 21. This add-on uses the Kura Maven Bundle Plugin
parent/BOM and JUnit 5. The matching Kura fork artifacts, including
`kura-osgi-test-support`, must already be installed in the Maven repository.
From a Kura workspace, build `build-support/pom.xml` and `kura/pom.xml` first.
Use the same `-Dmaven.repo.local=/absolute/cache` for generation and building if
an isolated repository is used.

```sh
git init
git add .
git commit -m "Initial add-on"
mvn verify
```

`mvn test` runs the ordinary component test. `mvn verify` additionally collects
actual bundle JARs and runs the Equinox/ConfigAdmin/SCR test in isolated storage,
then creates the distribution `.deb`. No device, Linux VM or external broker is
started. The distribution obtains its development version from the Git revision.

Import the root `pom.xml` in IDEA, select project JDK 21, and use its JUnit Run/Debug
for `ExampleComponentTest`. Before directly running `ExampleComponentIT`, run
`mvn verify` once to prepare `tests/${artifactId}.bundle.test/target/it-bundles`,
then use that test module as the working directory. Re-run Maven after changing
the bundle: the container executes its packaged JAR rather than IDEA output classes.

The bundle keeps its handwritten `META-INF/MANIFEST.MF`. The existing component and
metatype annotations explicitly generate `OSGI-INF` descriptors with Maven Bundle
Plugin. Package imports, start policy and Java 21 requirement stay in the Manifest;
add intentional exports there and in the bundle plugin configuration when needed.
The tests use actual bundle classloaders and service lookup, without putting Kura
business packages in the framework's system packages. Configuration-dependent
activation is checked before and after a real ConfigAdmin update.

Kura implementation and API versions are separate from the product version. When
upgrading them, update the root properties and test bundle collection coordinates
consistently. Signing remains opt-in with `-Psign-artifacts` and the existing
`addon.keystore.*` / `addon.key.*` properties; release packaging uses `-DreleaseBuild`.
