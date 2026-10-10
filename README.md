Eclipse Kura™
=============

<p align="center">
<img src="https://eclipse.dev/kura/images/kura.png" alt="Kura™ logo" width="500"/>
</p>

<div align="center">

[![GitHub Tag](https://img.shields.io/github/v/tag/eclipse/kura?label=Latest%20Tag)](https://github.com/eclipse-kura/kura/tags)
[![GitHub](https://img.shields.io/github/license/eclipse/kura?label=License)](https://github.com/eclipse-kura/kura/blob/develop/LICENSE)

[![Jenkins](https://img.shields.io/jenkins/build?jobUrl=https:%2F%2Fci.eclipse.org%2Fkura%2Fjob%2Fmultibranch%2Fjob%2Fdevelop&label=Jenkins%20Build&logo=jenkins)](https://ci.eclipse.org/kura/job/multibranch/job/develop/)
[![Jenkins](https://img.shields.io/jenkins/tests?compact_message&failed_label=%E2%9D%8C&jobUrl=https:%2F%2Fci.eclipse.org%2Fkura%2Fjob%2Fmultibranch%2Fjob%2Fdevelop%2F&label=Jenkins%20CI&passed_label=%E2%9C%85&skipped_label=%E2%9D%95&logo=jenkins)](https://ci.eclipse.org/kura/job/multibranch/) <br/>
  
</div>

## What is Eclipse Kura™?
From [the maori word for tank/container](https://maoridictionary.co.nz/search/?keywords=kura), Eclipse Kura™ is a versatile software framework designed to supercharge your edge devices. With an intuitive web interface, Eclipse Kura™ streamlines the process of configuring your gateway, connecting sensors, and IoT devices to seamlessly collect, process, and send data to the cloud. Eclipse Kura™ provides an extensible Java API for developing custom plugins within the framework. Additionally, it offers a REST API, enabling the use of Eclipse Kura™ as a backend service in your application.
 
Eclipse Kura™ runs on an edge gateway, which can be anything from a small SBC(single-board computer) like a Raspberry Pi, or a powerful high-performance computer.

### What can Eclipse Kura™ do for me?
* **Kura™ Services:** Provision and set up features to run on your gateway, such as an MQTT broker.
* **Kura™ Networking:** Manage Network connectivity, including 
* **Kura™ Wires:** Design data flows and data processing streams effortlessly with a drag-and-drop visual editor.
* **Kura™ Cloud Connectors:** Extendable cloud connector system. 
* **Kura™ Drivers:** Extendable service that handles reading data off of external devices.
* **Kura™ Snapshots:** Securely store and re-apply gateway settings for convenience.
* **Kura™ Security**: Easily and safely store your secrets.
* **Kura™ Container Orchestrator**: Manage Docker or Podman containers on your gateway for ultimate flexibility.
* **Kura™ AI Inference**: Run Nvidia Triton Models on the edge.
* **Kura™ Plugins**: Add and Extend the framework by adding your own Services, and Drivers.
* **Kura™ REST Service**: Embed the framework as a backend in your own edge applications.
 
### I have used Eclipse Kura™ to make a small-scale Edge deployment, how do I scale now?
If you want to scale, and manage many instances of Eclipse Kura™, check out [**Eclipse Kapua™**](https://github.com/eclipse/kapua). [Eclipse Kapua™](https://github.com/eclipse/kapua) is a Eclipse Kura™ compatible cloud command and control service that allows you to aggregate data and configure many Eclipse Kura™ devices. 

Documentation
-------------------

- [**User Documentation**](https://eclipse-kura.github.io/kura/latest/): here you'll find information on how to **use** Eclipse Kura™ i.e. installation instructions, informations on how to use the web UI and tutorials.
- [**Developer Documentation**](https://github.com/eclipse-kura/kura/wiki): the Eclipse Kura™ Github Wiki serves as a reference for **developers** who want to contribute to the Eclipse Kura™ project and/or develop new add-ons. Here you'll find Eclipse Kura™ development/release model, guidelines on how to import internal packages, creating new bundles and development environment tips & tricks.
- [**Docker Containers Documentation**](https://hub.docker.com/r/eclipse/kura/): the Eclipse Kura™ team also provides Docker containers for the project. Information on how to build and run them are available at the project's Docker Hub page.
- [**Developer Quickstart Guide**](https://github.com/eclipse-kura/kura#build): a quick guide on how to setup the development environment and build the project is also provided in this README.

Additionally, we provide two channels for reporting any issue you find with the project
- [**Github Issues**](https://github.com/eclipse-kura/kura/issues): for bug reporting.
- [**Github Discussions**](https://github.com/eclipse-kura/kura/discussions): for receiving feedback, asking questions, making new proposals and generally talking about the project.

Install
-------

This fork builds and runs with JDK 21. The management UI retains its Java 11 bytecode target for GWT compatibility.

### Target Gateways Installers
Eclipse Kura™ provides pre-built installers for common development boards. Check the following [link](https://www.eclipse.org/kura/downloads.php) to download the desired installers.
Take a look at [our documentation](https://eclipse-kura.github.io/kura/latest/getting-started/install-kura/) for further information on supported platforms and installer types.

### Docker Image
Eclipse Kura™ is also available as a [Docker container](https://hub.docker.com/r/eclipse/kura/).

Build
-----

### Prerequisites

Use **Maven 3.10, JDK 21 and JUnit 5**. The default build uses Maven Bundle Plugin
6.0.0 and preserves handwritten OSGi metadata. Check the JDK used by Maven with
`mvn --version`; setting only the IDEA project SDK does not set Maven's JDK.

This fork is a multi-repository workspace. Keep the sibling repositories listed in
`build-all.sh` beside `kura/`. Independently build the required PLC4X fork artifacts
from source into the same Maven repository before building YOFC. Missing required
siblings fail explicitly; they are not silently skipped. Docker is only required
when image building is enabled.

### Build the workspace

```sh
# Core and public build support only
mvn clean install

# Complete workspace and packages, without Docker images
BUILD_DOCKER=0 ./build-all.sh

# Ordinary tests, actual Equinox tests and HTTP/MQTT endpoint tests
RUN_TESTS=1 RUN_IT=1 BUILD_DOCKER=0 ./build-all.sh
```

The script builds public support and wrappers, core, sibling bundles/packages,
YOFC, core distribution and the development runtime in dependency order. Tests
are skipped by default. With Docker enabled (the script default), the final stage
builds matching ARM64 and AMD64 deb/image combinations in `kura-docker`.

Use `KURA_MAVEN_REPO=/absolute/cache` with `build-all.sh` or
`-Dmaven.repo.local=/absolute/cache` with direct Maven commands. PLC4X and all
consumers must use the same cache. Do not clean or reassemble an active IDEA
application's `target/runtime`; its persistent data lives separately in
`~/.kura-dev/<profile>`.

### Focused tests and packaging

```sh
mvn -f path/to/module/pom.xml test -Dtest=ClassName
mvn -Posgi-it -pl :kura-osgi-tests -am verify
mvn -f kura-endpoint-tests/pom.xml verify
mvn -f kura/distrib/pom.xml help:all-profiles
mvn -f kura/distrib/pom.xml install -Parch-aarch64,!arch-x86_64
```

Install the current core/sibling fixture artifacts before standalone endpoint
tests. Surefire and Failsafe reports are in each module's `target` directory.
`-DskipTests` skips ordinary tests; use `-DskipITs` as well when skipping Failsafe.
The [CI entry](docs/migration/ci-migration.md) invokes the complete tested workspace
command and filters reports against current source files. Badges above refer to
the upstream project, not a verified CI run for this fork.

IDE Setups
----------

Import the root `pom.xml` in IDEA with Maven 3.10 and JDK 21. Enable `workspace`
for sibling modules and the development runtime, `osgi-it` for real Equinox tests,
and `endpoint-it` for HTTP/MQTT tests. Shared application and JUnit Run/Debug
configurations are in `.run/`; see [runtime setup](kura-dev-runtime/README.md)
and [IDEA test acceptance](docs/testing/idea-junit-acceptance.md).

The [add-on archetype](docs/migration/addon-archetype-migration.md) generates an
ordinary Maven Bundle Plugin project with JUnit 5 and an isolated real Equinox
test. Legacy Eclipse/PDE resources remain where they have compatibility or
packaged-resource consumers. The default build and IDEA launch do not read P2.
See the [migration record](docs/migration/README.md) for exact validation boundaries
and outstanding restoration work.

Contributing
------------

Contributing to Eclipse Kura™ is fun and easy! To start contributing you can follow our guide [here](CONTRIBUTING.md).

### Acknowledgments

![YourKit Logo](https://www.yourkit.com/images/yklogo.png)

Thanks to YourKit for providing us an open source license of YourKit Java Profiler!

YourKit supports open source projects with innovative and intelligent tools
for monitoring and profiling Java and .NET applications.
YourKit is the creator of [YourKit Java Profiler](https://www.yourkit.com/java/profiler/),
[YourKit .NET Profiler](https://www.yourkit.com/.net/profiler/),
and [YourKit YouMonitor](https://www.yourkit.com/youmonitor/).
