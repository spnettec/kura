#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'main/resources/unfiltered/pkg/bin'))
import kura_recovery_launch as launch


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() == 0, 'Linux Root fixture required')
class LaunchProjectionTest(unittest.TestCase):
    identity = 'rec-11111111-1111-4111-8111-111111111111'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / 'launch'
        self.base.mkdir(mode=0o750)
        self.target = self.base / self.identity
        self.target.mkdir(mode=0o750)
        self.output = self.target / launch.OUT
        self.output.mkdir(mode=0o700)
        self.contents = b'exact staged snapshot'
        self.plan = dict(schema=1, restoreId=self.identity, root=launch.root_identity(self.root),
                         bindingSha256='a' * 64, activeKeySha256='b' * 64, ringSha256=None,
                         cohortSha256='c' * 64, bootstrapSha256='d' * 64, size=len(self.contents),
                         snapshotSha256=launch.digest(self.contents), mode='aes-gcm', passwordPolicy='authenticated')
        launch.write(self.target / launch.PLAN, launch.canonical(self.plan), 0o440)
        launch.write(self.target / launch.SNAPSHOT, self.contents, 0o440)
        launch.write(self.target / launch.REQUEST, launch.properties(self.target, self.plan), 0o440)

    def read(self, root=None):
        return launch.projection(self.base, self.identity, 0, 0, root or self.root)

    def test_projection_binds_snapshot_request_and_root(self):
        self.assertEqual((self.target, self.plan), self.read())
        with self.assertRaises(ValueError):
            self.read(self.base)
        snapshot = self.target / launch.SNAPSHOT
        snapshot.unlink()
        snapshot.symlink_to(self.target / launch.PLAN)
        with self.assertRaises(OSError):
            self.read()

    def test_request_replacement_and_non_private_result_directory_refused(self):
        request = self.target / launch.REQUEST
        request.unlink()
        changed = launch.properties(self.target, self.plan).replace(b'snapshot_0.xml', b'snapshot_1.xml')
        launch.write(request, changed, 0o440)
        with self.assertRaises(ValueError):
            self.read()
        request.unlink()
        launch.write(request, launch.properties(self.target, self.plan), 0o440)
        self.output.chmod(0o750)
        with self.assertRaises(ValueError):
            self.read()

    def test_claim_requires_exact_lease_and_cannot_be_replaced(self):
        lease = dict(keySha256=self.plan['activeKeySha256'], ringSha256=None,
                     cohortSha256=self.plan['cohortSha256'], startTicks='5')
        with patch.dict(os.environ, INVOCATION_ID='a' * 32):
            with self.assertRaises(ValueError):
                launch.claim(self.target, self.plan, lease | {'cohortSha256': 'e' * 64})
            self.assertFalse((self.output / launch.CLAIM).exists())
            launch.claim(self.target, self.plan, lease)
            with self.assertRaises(FileExistsError):
                launch.claim(self.target, self.plan, lease)
        saved = json.loads((self.output / launch.CLAIM).read_bytes())
        self.assertEqual(self.identity, saved['restoreId'])
        self.assertEqual(launch.digest(launch.canonical(self.plan)), saved['planSha256'])
        self.assertEqual(os.getpid(), saved['pid'])


if __name__ == '__main__':
    unittest.main()
