# SPDX-License-Identifier: EPL-2.0
"""Package-only continuation of an authenticated, still unissued retained layout."""
import hashlib
import hmac
import ctypes
import os
from pathlib import Path
import re
import subprocess
import tempfile


LAYOUT_REPAIR = 'layout-repair.json'


def checked_repair_source(api, raw, original, predecessor, recovery, secret):
    body = dict(schema=1, **predecessor, maintenanceId=original, phase='intent', recovery=recovery)
    tag = hmac.new(secret, b'kura-core-postinst-v1\0' + api.encoded(body), hashlib.sha256).hexdigest()
    api.require(raw == api.encoded(dict(body, tag=tag)), 'Retained layout repair does not match the original intent')


def layout_repair_receipt(api, policy, original, raw, recovery, predecessor, successor, secret):
    root = policy.root.lstat()
    evidence = dict(schema=1, purpose='kura-core-retained-layout-repair-v1', maintenanceId=original,
                    root=[root.st_dev, root.st_ino], originalIntentSha256=hashlib.sha256(raw).hexdigest(),
                    recovery=recovery, predecessor=predecessor, successor=successor)
    tag = hmac.new(secret, b'kura-core-retained-layout-repair-v1\0' + api.encoded(evidence), hashlib.sha256).hexdigest()
    return api.encoded(dict(evidence, tag=tag))


def admit_prelayout_repair(old_version, new_version):
    # These identities are build inputs from the reviewed predecessor DEB and
    # the finalized successor control. None is selected by the operator here.
    predecessor = _KURA_LAYOUT_REPAIR_PREDECESSOR
    require(predecessor is not None, 'Removal recovery copy requires the original package')
    require(os.environ.get('DPKG_MAINTSCRIPT_PACKAGE') == 'kura-core'
            and os.environ.get('DPKG_MAINTSCRIPT_NAME') == 'preinst'
            and os.environ.get('DPKG_ROOT', '') in ('', '/')
            and os.environ.get('DPKG_ADMINDIR') == '/var/lib/dpkg',
            'Retained layout repair requires the Core package preinst')
    for version in (old_version, new_version):
        require(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,199}', version), 'Invalid retained repair version')
    api = paired_lifecycle()
    policy = api.Lifecycle()
    target = dict(packageVersion=new_version, manifestSha256=_KURA_INCOMING_KEY_MANIFEST_SHA256,
                  postinstSha256=_KURA_LAYOUT_REPAIR_POSTINST_SHA256)
    require(predecessor['manifestSha256'] == target['manifestSha256'] and old_version in
            (predecessor['packageVersion'], new_version), 'Retained layout repair is not a control-only successor')
    subprocess.run(['/usr/bin/dpkg', '--compare-versions', new_version, 'gt', predecessor['packageVersion']],
                   check=True, timeout=10)
    physical = policy.path('/opt/eclipse') / _KURA_LAYOUT_REPAIR_HOME
    policy.directory(physical)
    require(hashlib.sha256(policy.read(physical/'libexec/key-backup/manifest.json', private=False)).hexdigest()
            == target['manifestSha256'], 'Unpaired retained layout payload')

    with policy.sender_locked(), policy.gwt_locked() as gwt, policy.recovery_locked(), policy.locked():
        policy.no_overrides()
        policy.check_records()
        policy.check_sender_admissions()
        if gwt is not None:
            gwt.check()
        policy.check_package_writers()
        require(not any(os.path.lexists(policy.path(path)) for path in
                        ('/opt/eclipse/.kura-preserve', '/var/lib/kura-recovery-launch/selection.json')),
                'Another maintenance copy or launch is still present')
        fence = policy.fence()
        require(fence and fence['firstAction'] == 'remove', 'Retained layout repair requires its original removal fence')
        original = fence['id']
        directory = policy.path('/var/lib/kura-package-configure') / original
        policy.directory(directory, private=True)
        names = {path.name for path in directory.iterdir()}
        require(names in ({'intent.json'}, {'intent.json', LAYOUT_REPAIR}),
                'Original layout or another configure phase is already issued')
        dpkg = subprocess.check_output(['/usr/bin/dpkg-query','-W','-f=${Status}\n${Version}', 'kura-core'],
                                       text=True, timeout=10).splitlines()
        # dpkg marks the installed source half-installed before invoking the
        # incoming preinst, and may restore unpacked after a refused preinst.
        states = ('install ok half-configured', 'install ok unpacked', 'install reinstreq half-installed')
        require(len(dpkg) == 2 and dpkg[0] in states
                and (dpkg[1] == predecessor['packageVersion'] or dpkg[1] == new_version and LAYOUT_REPAIR in names),
                'Retained layout package is outside the repair stop')
        continued = dpkg[1] == new_version
        control = policy.read(policy.path('/var/lib/dpkg/info/kura-core.postinst'), limit=512 * 1024, private=False)
        require(hashlib.sha256(control).hexdigest() ==
                (target if continued else predecessor)['postinstSha256'], 'Unpaired installed Core postinst')

        state = policy.main_unit_properties('MainPID', 'ControlPID', 'ActiveState')
        require(state['MainPID'] == state['ControlPID'] == '0' and state['LoadState'] == 'not-found'
                and state['ActiveState'] == 'inactive', 'Original Main layout is already active or installed')
        require(not any(os.path.lexists(policy.path('/lib/systemd/system/' + name))
                        for name in (*api.NATIVE_MAIN_UNITS, 'kura.service')), 'A vendor unit was already restored')
        logical = policy.path('/opt/eclipse/kura')
        if os.path.lexists(logical):
            policy.directory(logical)
            owners = subprocess.check_output(['/usr/bin/dpkg-query', '-S', '/opt/eclipse/kura'], text=True, timeout=10)
            require(not any(logical.iterdir()) and owners.splitlines() == ['kura-core: /opt/eclipse/kura'],
                    'Unexpected retained Main directory')

        secret = policy.read(policy.state/'journal.key', limit=32)
        require(len(secret) == 32)
        retained = policy.path('/var/lib/kura-retained')
        policy.directory(retained, private=True)
        require(not os.path.lexists(retained / '.partial-payload'), 'Original retained layout is incomplete')
        saved = retained.lstat()
        recovery = dict(mode='reinstall', device=saved.st_dev, inode=saved.st_ino)
        raw = policy.read(directory/'intent.json', limit=4096)
        checked_repair_source(api, raw, original, predecessor, recovery, secret)
        require(prepare_retained_generation(unpacked_layout=True) == 0, 'Original retained credentials are unpaired')
        receipt = layout_repair_receipt(api, policy, original, raw, recovery, predecessor, target, secret)
        path = directory / LAYOUT_REPAIR
        if LAYOUT_REPAIR in names:
            require(policy.read(path, limit=4096) == receipt, 'Original layout repair authorization changed')
        else:
            # A crash during staging leaves the original configure directory unchanged.
            with tempfile.TemporaryDirectory(prefix=f'.{original}-repair-', dir=directory.parent) as pending:
                staged = Path(pending) / LAYOUT_REPAIR
                policy.create(staged, receipt)
                rename = ctypes.CDLL(None, use_errno=True).renameat2
                rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
                rename.restype = ctypes.c_int
                if rename(-100, os.fsencode(staged), -100, os.fsencode(path), 1):
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error), str(path))
                policy.sync(directory)
