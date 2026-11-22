# Service PID runtime probe

Build this test bundle with JDK 21 using the OSGi framework and Configuration Admin APIs.
Package the compiled classes with the adjacent manifest. Load the bundle in a fresh
isolated runtime with the real providers under test. The distribution does not include
the probe.

Create `/opt/eclipse/kura/data/service-pid-probe` as a private directory writable by the
test JVM user. Put one row per service in `contracts.tsv`, using five tab-separated
columns in this order.

1. Registering bundle symbolic name
2. Declarative Services component name
3. Service interface
4. Expected `service.pid`
5. `observe` or `cycle`

The probe looks up the real registrations with OSGi filters and records whether each PID
already has a matching Configuration Admin record. Review `survey.tsv` before creating
the empty `cycle.request` file. A cycle requires the matching Configuration Admin
record to be absent. The probe creates a temporary marker configuration, verifies it
through a service filter, removes it in a finally block, and verifies the absent state
again. Each observation checks the provider and the exact scalar String property.
Read `transitions.tsv` for the three states of each requested cycle and `failure` for
errors. Stop the fixture and remove the test bundle from its load path after verification.
