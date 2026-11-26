# SPDX-License-Identifier: EPL-2.0
"""Debian snapshot qualifiers must stay wider than historical 12-digit builds."""
import unittest
from pathlib import Path


def debian_upstream_greater(left, right):
    """Compare the numeric git timestamp embedded after '~git'."""
    def stamp(version):
        token = version.split('~git', 1)[1]
        digits = []
        for char in token:
            if char.isdigit():
                digits.append(char)
            else:
                break
        return int(''.join(digits))
    return stamp(left) > stamp(right)


class DebianVersionQualifierTest(unittest.TestCase):
    def test_fourteen_digit_successor_sorts_after_both_historical_widths(self):
        successor = '3.0.0~git20261126031500.abcdef1-1'
        self.assertTrue(debian_upstream_greater(successor, '3.0.0~git202611251924.15ebcda-1'))
        self.assertTrue(debian_upstream_greater(successor, '3.0.0~git20261125044831.98ce41482f-1'))
        self.assertFalse(debian_upstream_greater('3.0.0~git202611251924.15ebcda-1',
                                                 '3.0.0~git20261125044831.98ce41482f-1'))

    def test_debug_package_snapshots_use_second_resolution(self):
        workspace = Path(__file__).resolve().parents[5]
        expected = '<maven.build.timestamp.format>yyyyMMddHHmmss</maven.build.timestamp.format>'
        missing = []
        for path in (
            workspace / 'kura/kura/distrib/pom.xml',
            workspace / 'kura-networking/distrib/pom.xml',
            workspace / 'kura-deployment/distrib/pom.xml',
            workspace / 'kura-wires/distrib/pom.xml',
            workspace / 'kura-cloud/distrib/pom.xml',
            workspace / 'kura-camel/distrib/pom.xml',
            workspace / 'kura-artemis/distrib/pom.xml',
            workspace / 'kura-container/distrib/pom.xml',
            workspace / 'kura-opcua/distrib/pom.xml',
            workspace / 'kura-position/distrib/pom.xml',
            workspace / 'kura-triton/distrib/pom.xml',
            workspace / 'kura-management-ui/distrib/pom.xml',
            workspace / 'kura-yofc-runtime/distrib/pom.xml',
        ):
            text = path.read_text()
            if 'package.snapshot' in text and expected not in text:
                missing.append(str(path.relative_to(workspace)))
        self.assertEqual([], missing)


if __name__ == '__main__':
    unittest.main()
