# macOS Tamper SCR acceptance fixture

This opt-in test bundle registers a simulated `TamperDetectionService` with
`kura.service.pid=fixture.tamper.mac.scr`. Its Gogo `tamperprobe:trigger` command
sets a tampered state and sends a real `TamperEvent` through EventAdmin. The REST
`_reset` endpoint clears that state and sends a second event. The fixture counts
events delivered back through an OSGi `EventHandler`. It does not use a physical
tamper sensor and is not included in the production reactor or distribution.

Build with JDK 21, Maven 3.10 and the same local Maven repository as the core
workspace:

```sh
mvn -f kura-dev-runtime/acceptance/tamper-probe/pom.xml \
  -Dmaven.repo.local=/absolute/workspace/maven-cache package
```

Start an isolated macOS development runtime whose HTTPS certificate and admin
identity are under your control. Do not use a personal `~/.kura-dev` profile. In
its Gogo console, run:

```text
install file:/absolute/kura-dev-runtime/acceptance/tamper-probe/target/kura-tamper-acceptance-fixture-1.0.0-SNAPSHOT.jar
start <bundle-id-from-install>
tamperprobe:trigger
tamperprobe:events
```

Use certificate-validated, authenticated HTTPS against that isolated runtime:

- `GET /services/tamper/v1/list` must show the fixture PID and display name.
- `GET /services/tamper/v1/pid/fixture.tamper.mac.scr` reports false before
  trigger and true after trigger.
- `POST /services/tamper/v1/pid/fixture.tamper.mac.scr/_reset` returns 204;
  the following GET reports false, and `tamperprobe:events` returns 2.
- `uninstall <bundle-id>` removes the service. The list returns `[]` and the
  PID status route returns 404.

Stop the isolated runtime after the probe. This validates actual SCR dynamic
binding, EventAdmin delivery and HTTPS REST behavior on macOS. It does not
validate a Debian installation or physical hardware.
