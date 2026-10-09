# Default SSL keystore regression found by restored tests

Compared with upstream `e500a68d7b3f4a970aca3e13c038947269278827`, the local `getSSLContextInternal` has an extra alias fallback introduced by `28de3557bb` (2019-11-25, `add fastjson`). It opened the keystore file even when the default OSGi service configuration supplied no filename. Upstream directly uses its bound `KeystoreService` in that case and has no unconditional file access. This is a historical local defect, unrelated to Maven Bundle Plugin.

The fix only loads a store to evaluate the alias fallback when an alias was requested. With no filename, it uses the bound service; explicit file paths retain their existing behavior. The existing empty-store fallback and SSL context caching remain in place. Service failures retain their cause as `KeyStoreException`.

`SslManagerServiceImplTest` now has 11 passing JUnit 5 cases: four upstream cache invalidation scenarios, default/alias/file-path regressions, and private-key/trusted-certificate operations. Two previously disabled upstream cases were rewritten around the current `KeystoreService` contract using generated matching certificates rather than an absent `cert` resource or direct file persistence assumptions. All temporary files use `@TempDir`.

Validation with Maven 3.10 and JDK 21:

```sh
mvn -pl :org.eclipse.kura.core -am test
```

The core bundle reports 73 tests, with zero failures, errors, or skipped cases. The source MANIFEST, DS metadata, runtime SSL configuration, and production dependency versions are unchanged.
