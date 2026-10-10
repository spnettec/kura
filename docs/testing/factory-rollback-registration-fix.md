# Factory configuration rollback registration

With an actual CM factory and SCR service, rolling back an active instance invoked
registerComponentConfiguration again. The fork's duplicate-PID protection then
deleted that same CM configuration and unregistered the instance. For a newly
recreated factory, rollback also marked it active before SCR could publish its
service, so the later legitimate registration hit the same protection.

Rollback now updates already active instances without registering them again.
Inactive/recreated factories have their service/factory mapping recorded and stay
in the existing waiting-for-activation set until SCR binds the actual service.
The local duplicate-PID guard remains unchanged. Snapshot encryption, passwords,
localized metadata and handwritten OSGi descriptors are not altered.

Two focused regression tests failed before this repair: the existing target was
deleted, and the new target was incorrectly marked active. Both pass afterward.
Full core.configuration install passed 46 tests; the existing configuration unit
suite passed 82. Maven 3.10.0 / Temurin 21 / JUnit 5, isolated migration-m2.
The separate configuration runtime fixture exercises real factory updates and
rollback, including Password type/value preservation.
