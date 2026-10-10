# Legacy NetworkService enumeration

The legacy core NetworkServiceTest belongs with the networking sibling. Four
meaningful scenarios now execute in LegacyNetworkServiceTest using the actual
NetworkServiceImpl: component/API presence, names, all interface DTOs and active
interface DTOs. The old `assertTrue(true)` dummy test is omitted.

LinuxNetworkUtil, USB/EventAdmin and the static auto-connect lookup are controlled
boundaries. Three deterministic interfaces replace assumptions about the executing
machine. Names, types, states and non-null address collections retain the upstream
assertions. Active enumeration additionally proves the current implementation's
hasAddress predicate: an interface marked up without an address is excluded.
Each fixture stops the service executor and closes its static mock.

The service-presence case establishes the component/API contract here, not actual
SCR registration. Real Linux interfaces, kernel state, NetworkManager/D-Bus and
IDEA execution remain runtime acceptance. No host interface is configured and no
D-Bus connection is made. The previously upgraded dbus-java 5.2.0 with virtualthreads
and YOFC Update/Activate behavior are unchanged; upstream Reapply is not restored.

Validation: four new cases passed; the full linux.net module then passed **141**
tests with zero failures/errors/skips under Maven 3.10.0 / Temurin 21 / JUnit 5.
Networking commit `994f131` changes only this test source. No production dependency,
network behavior, handwritten metadata, YOFC or PLC4X code was changed.
