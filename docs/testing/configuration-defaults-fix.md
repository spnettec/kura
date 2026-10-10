# Default configuration retrieval repair

Real Equinox configuration scenarios exposed two old defects in
getDefaultComponentConfiguration: password defaults were returned still encrypted,
and SelfConfiguringComponent defaults had no definition or properties. The local
method still contained the 2016/2017 implementation; upstream 9ade614a40 (#4067)
already documents this retrieval repair. These are independent of the fork's
snapshot encryption switch and localized metadata API.

The method now obtains a self-configuring component's validated definition through
the existing local lookup (which releases its service reference), derives defaults
from that definition, and decrypts Password values at the public API boundary.
It does not return the component's currently configured values. Empty/missing
ordinary definitions retain their existing empty result. Snapshot persistence,
factory registration/activation, handwritten DS metadata and API exports are unchanged.

Four regression invocations include both failures and null/empty-PID controls.
Before the repair, two failed: encrypted password versus expected clear Password,
and absent self-component metadata. After the repair all four pass. Full bundle
install passed 44 tests, and the existing ConfigurationServiceJunitTest passed all
82 cases with Maven 3.10.0 / Temurin 21 / JUnit 5 in migration-m2. The separate real
Equinox fixture restoration adds actual CM/SCR/XML/CryptoService coverage.
