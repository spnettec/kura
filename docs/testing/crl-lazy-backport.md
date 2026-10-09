# CRL lazy-storage backport

Upstream `8b605b9af04bb2123ca70544be0dd534ceee7dc5` (#6403, 2026-09-28) was already recorded as the second parent of the selective-port marker `d3abd8257abd635d929d6616e5d0b0bd88f2e5ac`. Its production changes were missing from that tree and every later merge. The marker's adopted/skipped lists did not document a deliberate exclusion of #6403. A regular subsequent merge therefore cannot recover the omitted diff.

The four production files are backported independently of the Maven test restoration. CRL JSON now retains distribution points, issuer, next update and a body filename; DER bodies are stored in `<store>.d/<sha256>.crl` and decoded on demand. Old JSON with inline `body` is migrated on first load. Keep the JSON file and its adjacent `.d` directory together when backing up or moving a keystore CRL cache. Snapshots and keystore entries are unaffected.

The fork's Java 21 virtual-thread download executor and recurring debug logs remain unchanged. CRL network enablement and verification configuration are also unchanged.

The upstream five storage scenarios were moved to JUnit 5 with isolated `@TempDir` files and store cleanup. Two additional cases verify that metadata queries do not read a deleted DER body and that a missing referenced body is rejected. All seven pass under Maven 3.10 and JDK 21:

```sh
mvn -pl :org.eclipse.kura.core.keystore -am test \
  -Dtest=StoredCRLLazyDecodeTest -Dsurefire.failIfNoSpecifiedTests=false
```

Broader local HTTP/download integration scenarios are separate Failsafe tests; their acceptance is recorded with the upstream restoration inventory after they pass.
