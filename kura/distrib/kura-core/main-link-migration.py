# SPDX-License-Identifier: EPL-2.0
"""Explicit Main link migration embedded in the guarded Core preinst."""
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from kura_key_service_lifecycle import MAIN_LINK_BACKUP, MAIN_LINKS, MAIN_VENDOR_PATHS, require


def link_snapshot(lifecycle, link):
    lifecycle.directory(link.parent)
    before = link.lstat()
    require(stat.S_ISLNK(before.st_mode) and before.st_uid == lifecycle.owner and before.st_nlink == 1,
            'Main link is not Root-owned')
    target = os.readlink(link)
    after = link.lstat()
    identity = lambda m: (m.st_dev, m.st_ino, m.st_ctime_ns, m.st_mtime_ns)
    require(identity(before) == identity(after), 'Main link changed during migration')
    require(Path(target).is_absolute() and str(Path(target)) == target and Path(target).name == 'kura.service',
            'Main link target requires reviewed migration')
    return target, identity(after)


def stopped_main_layout(lifecycle):
    properties = lifecycle.main_unit_properties('ActiveState', 'MainPID', 'ControlPID', 'Job')
    fields = dict(Id='kura.service', Names='kura.service', LoadState='loaded', SourcePath='',
                  DropInPaths='', Transient='no', ActiveState='inactive', MainPID='0', ControlPID='0', Job='')
    require(all(properties[key] == value for key, value in fields.items()),
            'Main must be inactive with a single clean effective unit and no queued job')
    return properties


def migrate_linked_main(lifecycle):
    """Normalize an explicitly selected package-paired link under the installer locks."""
    lifecycle.no_overrides()
    with lifecycle.sender_locked(), lifecycle.gwt_locked() as gwt, lifecycle.recovery_locked(), lifecycle.locked():
        lifecycle.check_sender_admissions()
        if gwt is not None:
            gwt.check()
        lifecycle.check_records()
        require(lifecycle.fence() is None and not any(os.path.lexists(lifecycle.path(path)) for path in (
            '/var/lib/kura-retained', '/opt/eclipse/.kura-preserve')),
            'Finish existing package maintenance before Main link migration')
        manifest = lifecycle.assets()
        expected = lifecycle.main_unit_digest(manifest)
        vendor = lifecycle.main_vendor_path()
        lifecycle.directory(vendor.parent)
        for path in map(lifecycle.path, MAIN_VENDOR_PATHS):
            if os.path.lexists(path):
                require(path.parent.resolve(strict=True) / path.name == vendor,
                        'Ambiguous vendor Main paths')
        candidates = [(choice, lifecycle.path(path)) for choice, path in MAIN_LINKS.items()]
        candidates += [(choice, link.with_name(MAIN_LINK_BACKUP)) for choice, link in candidates]
        selected = [(choice, link) for choice, link in candidates if os.path.lexists(link)]
        require(len(selected) == 1, 'Expected exactly one Root Main link or saved migration link')
        choice, link = selected[0]
        original = lifecycle.path(MAIN_LINKS[choice])
        saved = original.with_name(MAIN_LINK_BACKUP)
        target, identity = link_snapshot(lifecycle, link)
        unit = lifecycle.read(lifecycle.path(target), private=False)
        require(hashlib.sha256(unit).hexdigest() == expected, 'Linked Main differs from its package')
        layout = stopped_main_layout(lifecycle)
        lifecycle.assets(generation_binding=True, _linked_main_unit=unit)
        if link == original:
            require(layout['UnitFileState'] == choice and layout['FragmentPath'] == MAIN_LINKS[choice]
                    and layout['NeedDaemonReload'] == 'no', 'Main link is not the loaded package definition')
            if not os.path.lexists(vendor):
                with tempfile.NamedTemporaryFile(dir=vendor.parent, prefix='.kura-main-', mode='wb') as staged:
                    staged.write(unit)
                    staged.flush()
                    os.fchmod(staged.fileno(), 0o644)
                    os.fsync(staged.fileno())
                    os.link(staged.name, vendor)
                lifecycle.sync(vendor.parent)
        else:
            require(layout['FragmentPath'] in (*MAIN_VENDOR_PATHS, MAIN_LINKS[choice])
                    and layout['UnitFileState'] in (choice, 'disabled', 'static'),
                    'Saved link cannot explain the effective Main layout')
        require(lifecycle.read(vendor, private=False) == unit, 'Existing vendor Main differs from the linked package')
        require(link_snapshot(lifecycle, link) == (target, identity) and stopped_main_layout(lifecycle) == layout,
                'Main link or manager state changed during migration')
        if link == original:
            require(not os.path.lexists(saved), 'Main migration link already exists')
            original.rename(saved)
            lifecycle.sync(saved.parent)
        saved_snapshot = link_snapshot(lifecycle, saved)
        require(saved_snapshot[0] == target, 'Saved migration link changed')
        lifecycle.command(['daemon-reload'])
        result = stopped_main_layout(lifecycle)
        require(result['UnitFileState'] in ('disabled', 'static'),
                'Migrated Main would be enabled or overridden')
        lifecycle.paired_main_unit(manifest, result['UnitFileState'])
        require(link_snapshot(lifecycle, saved) == saved_snapshot, 'Saved migration link changed')
        saved.unlink()
        lifecycle.sync(saved.parent)
