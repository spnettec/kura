# Legacy test helper source audit

Eight outstanding test-support sources have now been reviewed against their
existing migrated consumers. This closes inventory bookkeeping; it does not add
eight tests or claim that the legacy OSGi harness has executed.

| Upstream source | Current implementation / disposition |
| --- | --- |
| ChannelDescriptorTestDriver | Already ported into kura-wires REST wire tests; restored helper |
| ChannelDescriptorTestDriverOptions | Explicit driverDefinition OCD/defaults in RestGraphFixture; restored helper |
| GraphBuilder | RestGraphFixture owns graph construction and real graph-service calls |
| TestEmitterReceiver | Explicit endpoint metadata and recording WireSupport callbacks in consumer fixtures |
| TestEmitterReceiverOptions | Explicit empty OCD and port cardinalities in emitterDefinition |
| WireTestUtil | Explicit component lifecycle, graph operations and bounded consumer waits |
| core.testutil.service.ServiceUtil | EquinoxRuntime scoped service handles plus per-fixture lifecycle |
| EventAdminUtil | Owned queues and bounded waits in keystore CRL / HTTP manager fixtures |

The last six are recorded as replaced legacy harness sources. Their global
FrameworkUtil discovery, factory/graph-arrival chains and one-shot event futures
are not brought back into the plain Maven test classpath. Production ServiceUtil
is a separate retained implementation. The initial helper review left full SCR,
ConfigurationAdmin factory arrival, EventAdmin routing and WireAdmin graph delivery
for runtime acceptance.

The 2026-10-11 evidence reconciliation confirms that the later complete Mac
application covered SCR/factory lifecycle, EventAdmin and production Timer-to-Logger
routing (`mac-full-runtime-business-validation-20261010.json`). The isolated Mac
WireAdmin service and route acceptance and the complete driver/OCD fixture acceptance
are recorded in `mac-wire-scr-service-validation-20261010.json`,
`mac-wire-route-scr-validation-20261010.json` and
`mac-complete-wire-fixture-validation-20261010.json`. Deployed gateway and installed
Debian sibling package acceptance remain deferred in the inventory. These existing
results are not rerun or added to invocation totals by this reconciliation.

Review found an upstream test-only descriptor-builder typo: withMin and withoutMin
assigned max. kura-wires commit 4d304a9 corrects the helper and both REST descriptor
expectations now include all eight minimum bounds. Existing local i18n/description
and DataType choices are retained. Full REST wire module: 49 passing tests, zero
failures/errors/skips, Maven 3.10.0 / Temurin 21. These invocations are existing
coverage revalidated after the fixture fix, not 49 newly restored tests.

The HTTP manager's ten scenarios and cleanup checks validate its event-queue
replacement. Prior passing consumer reports remain separately documented; no
workspace-wide rerun is claimed by this audit.
