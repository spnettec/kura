# H2 database factory metadata repair

The local handwritten `org.eclipse.kura.core.db.H2DbService.xml` duplicated the
H2DbServer definition: wrong OCD ID, factory PID, localization resource and three
server attributes. Comparing merge `c57ee12400` with its upstream parent pinpoints
the replacement. The original upstream XML at `b231173250` correctly defined the
database service. The current upstream develop head was independently checked as
`e500a68d7b3f4a970aca3e13c038947269278827`; its
[H2DbServiceMetatype](https://github.com/eclipse-kura/kura/blob/e500a68d7b3f4a970aca3e13c038947269278827/kura/org.eclipse.kura.db.h2db.provider/src/main/java/org/eclipse/kura/internal/db/h2db/provider/H2DbServiceMetatype.java)
still defines the corresponding six database fields using annotations.

An actual Equinox regression first demonstrated that explicitly supplying a JDBC
URL can still create a database and execute SQL. The more specific factory discovery
assertion failed twice: ConfigurationService did not advertise H2DbService. This
is a metadata/default-configuration defect, not evidence that every existing
database instance failed to start.

The repair restores the database OCD/factory ID and six typed fields in the
handwritten XML. Field IDs, types, cardinalities, required flags, bounds and defaults
match the original upstream XML, including the 15-minute metatype defrag default.
The existing Java fallback of 20 minutes is unchanged, as are explicitly configured
values. The local `H2DbService_en.properties` and `_zh.properties` remain byte-identical;
the XML now references their existing keys. H2DbServer, manifests, annotation
generation and production Java are unchanged.

Validation on macOS Maven 3.10/JDK 21/Jupiter:

- All 41 H2 provider tests pass and the artifact installs to the isolated cache.
- Both CloudFactoryRuntimeIT invocations now pass with actual SCR, ConfigurationService
  and H2: database/server factory discovery, typed defaults, SQL `SELECT 42`, English
  and Chinese names, six attributes and existing cloud/publisher lifecycle checks.
- The packaged XML matches source; the before/after reports, logs and upstream
  references are archived. See [checksums and evidence](h2-factory-metatype-validation-20261010.json).

The production repair is committed separately from the Cloud runtime test changes.
This adds no broker/TLS, file-persistence or Linux acceptance claim and does not
rewrite the earlier two-test report or historical full workspace totals.
