# SQLite provider with SQLCipher for Linux ARM64

This optional Kura deployment package delivers the SQLite provider and Xerial JDBC together. The JDBC bundle contains a Linux ARM64 JNI linked to the distribution's SQLCipher. The gateway needs the shared-library ABI used to build the DP. Debian 13 provides `libsqlcipher1` and Ubuntu 26.04 provides `libsqlcipher2`. Install the DP through Kura's deployment package interface. A plain Xerial JDBC or SQLite provider already installed under a different owner must be reconciled before installing this DP.

On a GNU/Linux ARM64 build host use JDK 21, Maven, a C compiler, pkg-config and `libsqlcipher-dev`. From the Core checkout, use the same Maven repository and build qualifier for build-support, the Core provider and the distribution:

```sh
qualifier=$(git show -s --format=%ct HEAD)
repo=${KURA_MAVEN_REPO:-"$HOME/.m2/repository"}
mvn -Dmaven.repo.local="$repo" -Dkura.build.qualifier="$qualifier" -f build-support/pom.xml install
mvn -Dmaven.repo.local="$repo" -Dkura.build.qualifier="$qualifier" -f kura/pom.xml -pl org.eclipse.kura.db.sqlite.provider -am install
mvn -Dmaven.repo.local="$repo" -Dkura.build.qualifier="$qualifier" -f kura/distrib/kura-sqlite-dp/pom.xml package
```

The full distribution reactor also includes the module with `-Psqlcipher-dp`. The DP is written to `kura/distrib/kura-sqlite-dp/target/`. Use a newer build qualifier when publishing an update to an installed DP. The JDBC bundle version includes that qualifier and the JNI SHA-256 so Deployment Admin can identify the native revision. Updating or removing the DP uses Kura's normal deployment package lifecycle. Database files, encryption settings and credentials belong to the gateway.
