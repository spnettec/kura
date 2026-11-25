# Optional SoftHSM file-token module

Use this package for Linux file-backed tokens that must recover within the same
JVM after their original directory or token metadata is temporarily unavailable.
The source archive contains SoftHSM 2.6.1 plus the original-file recovery and
fork-test fixes. `source.sha256` pins the archive and the package records the Git
revision and native module digest.

## Build

On a Debian build host install CMake, make, a C++ compiler, Git, pkg-config,
OpenSSL and CppUnit development headers, and dpkg-dev. Use JDK 21 and the project
Maven version. Run from the Kura repository root.

```sh
mvn -f kura/distrib/kura-softhsm2-file/pom.xml package
```

The `softhsm-file-package` profile also includes the module in the distribution
reactor. The Debian package is written to this module's `target` directory. Compilation
uses the build host's Debian architecture and dpkg derives library dependencies
from the executable. The OpenSSL legacy provider configuration applies to the
upstream test suite during the build.

## Use

Install the native package and point the Kura PKCS#11 keystore's `library.path`
at `/usr/lib/kura-pkcs11/softhsm2/libsofthsm2.so`. The module reads the site
configuration from `/etc/kura-pkcs11/softhsm2-file.conf` by default. Use the existing file
store directory and the same slot binding and credentials. Give the Kura service
account access to the site configuration and token store using the site's
existing ownership policy. The package owns the module and its documentation.
Distribution SoftHSM and other PKCS#11 libraries can coexist.

Stop Main before replacing or removing a module it uses. Package removal leaves
site PKCS#11 configuration, tokens, and Kura snapshots available for a later
reinstall. Restore the module before starting a Main that is configured to use it.
