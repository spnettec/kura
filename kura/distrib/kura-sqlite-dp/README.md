# SQLite provider with SQLCipher for Linux ARM64

This optional Kura deployment package delivers the SQLite provider and Xerial JDBC together. The JDBC bundle contains a Linux ARM64 JNI linked to the distribution's SQLCipher. The gateway needs the matching SQLCipher shared-library ABI (Debian 13 package `libsqlcipher1`). Install the DP through Kura's deployment package interface. A plain Xerial JDBC or SQLite provider already installed under a different owner must be reconciled before installing this DP.

On a GNU/Linux ARM64 build host use JDK 21, Maven, a C compiler, pkg-config and `libsqlcipher-dev`. From the Core checkout, use the same Maven repository and build qualifier for build-support, the Core provider and the distribution:

```sh
mvn -f build-support/pom.xml install
mvn -f kura/pom.xml -pl org.eclipse.kura.db.sqlite.provider -am install
mvn -f kura/distrib/kura-sqlite-dp/pom.xml package
```

The full distribution reactor also includes the module with `-Psqlcipher-dp`. The DP is written to `kura/distrib/kura-sqlite-dp/target/`. Updating or removing it uses Kura's normal deployment package lifecycle. Database files, encryption settings and credentials belong to the gateway. Changes to those are independent of updating the DP.
