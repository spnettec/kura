# OSGi utility test restoration

2026-10-10. Twelve restored cases pass against an actual embedded Equinox 3.24.100
framework: all nine SingleServiceTracker scenarios and three generic BundleUtil
scenarios. The full util module reports 133 tests, zero failures/errors/skips on
Maven 3.10.0/JDK 21/Jupiter. Existing provided Equinox supplies the framework; no POM,
production or handwritten metadata changes in this restoration batch.

Each case uses isolated temporary framework storage, bounded shutdown and explicit
tracker cleanup. Service ranking, equal-rank registration order, removal fallback,
late arrival and ranking modifications use real service registrations and events.
Bundle filters inspect two actual temporary bundles, Runnable/Callable registrations
and exact bundle sets. Four GPIO-specific upstream cases are excluded. The upstream
containsAll-self assertion is replaced with exact equality; no GPIO API is restored.

This validates the utility behavior with Equinox. Kura SCR/factory/configuration
assembly and IDEA execution are separate pending acceptance items.

Source review found SingleServiceTracker obtains services without releasing them in
its customizer removal path. A separate regression/fix will verify real framework
service usage cleanup; the passing upstream ranking tests alone do not cover it.

## Separate service-reference cleanup repair

Three new regression executions failed before the fix, using real Equinox
ServiceFactory acquisition/release counts and ServiceReference.getUsingBundles().
Both selected and nonselected references leaked on tracker close or when modified
properties no longer matched the tracker filter. The removal path now releases each
successfully removed reference in finally, including the nonselected early return.
Repeated close does not release twice. Ranking and notification behavior are unchanged.

All 136 util tests and isolated bundle installation pass on Maven 3.10.0/JDK 21,
zero failures/errors/skips. No OSGi metadata changes; production repair is a separate
commit from the upstream test restoration. Source inventory remains 68 unreviewed.
