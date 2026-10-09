# Event publisher and role-store restoration

2026-10-10. Two EventPublisher scenarios and all ten RoleRepositoryStoreTest methods
pass on Maven 3.10.0/JDK 21/Jupiter. Full event publisher module reports 24 tests and
role store reports ten, zero failures/errors/skips. No production changes in this
restoration batch. Useradmin adds only test-scoped Jupiter, Mockito, Log4j API and
OSGi Event API dependencies.

Event publication checks null rejection, original payload identity, the returned
message ID and all six current message properties. Topic prefix and topic are explicit
fixture inputs, while QoS 0/retain false/priority 7 preserve current defaults. A scoped
helper-construction mock replaces the old private-field overwrite and does not leak
an abandoned tracker. Actual SCR/cloud/MQTT integration remains separate.

Role tests use the real Felix UserAdminImpl, RoleRepository and role objects, including
property/credential change notifications. A controlled dispatcher forwards the actual
events to Kura's store. The scheduled callback verifies the existing 5000ms delay,
then executes serialization and captures ConfigurationService updates. Self-update
acknowledgement follows the production path. Tests preserve both USER/GROUP variants,
byte/string properties and credentials, removal and sorted basic/required memberships.
The default test inspects activated production options rather than test-only defaults.
Schedulers are shut down; no shared user repository or gateway configuration changes.
Actual EventAdmin/SCR/ConfigurationService assembly remains deferred.

EventPublisher source review found that update replaces its endpoint helper without
closing the previous tracker, and deactivate does not shut down its owned virtual-thread
executor. The restoration fixture explicitly cleans up that executor pending a separate
production regression/fix.
