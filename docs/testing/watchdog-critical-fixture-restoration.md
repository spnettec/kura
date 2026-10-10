# Critical watchdog fixture restoration

The upstream FailingCriticalComponent has no JUnit methods: it is a manual runtime
component that registers a 30-second critical service and never checks in. It is
retained unchanged under the Linux watchdog module's test source tree, without a
production bundle or automatically activated DS descriptor.

A new Jupiter scenario binds the real WatchdogServiceImpl registration logic,
checks the PID and timeout, advances the registration timestamp to assert expiry,
and verifies deactivation removes the component. No poll executor is activated,
no hardware device is opened and no reboot command is executed. Physical watchdog
reboot behavior and deployed DS wiring remain separate acceptance work.

Maven 3.10.0 / Temurin 21: the complete Linux watchdog module passes 10 tests (nine
existing plus one fixture scenario), zero failures/errors/skips. The only dependency
addition is the test-scoped OSGi component API used by the upstream lifecycle methods.
