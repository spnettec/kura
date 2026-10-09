# Deployment package builder

This ordinary Maven plugin implements the bundle-only deployment packages used by
Kura siblings and YOFC. It has no Tycho, PDE, target-platform or Eclipse dependency.

* `build`: attach the current project's packaged bundle as a `.dp`.
* `package`: attach the explicitly declared compile/runtime dependency bundles.
  Private and transitive dependencies are not installed as separate bundles.

Both goals bind to `package`, attach type `dp`, and preserve the existing filename
`${artifactId}_${version}.dp` and entries `${Bundle-SymbolicName}_${Bundle-Version}.jar`.
The DP manifest records the exact bundle names and versions. Snapshot DP versions
use `kura.build.qualifier`; release versions remain unchanged. Bundle bytes are copied
unchanged and ZIP timestamps are fixed. `-Dosgi-dp.skip=true` skips packaging.

Missing artifacts, duplicate symbolic names, malformed versions and missing
`Bundle-ClassPath` entries fail the build. This plugin intentionally does not implement
the old plugin's unused Tycho feature traversal, resource processors or fix packages.
Those require explicit implementation before adding a consumer.

Format reference: [OSGi Deployment Admin specification](https://docs.osgi.org/specification/osgi.cmpn/7.0.0/service.deploymentadmin.html).
