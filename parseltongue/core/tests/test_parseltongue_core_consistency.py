"""Self-validation: load core.pltg and check consistency."""

import os
import unittest

from ..loader import load_pltg

CORE_PLTG = os.path.join(os.path.dirname(__file__), "..", "validation", "core.pltg")


class TestParseltongueCoreConsistency(unittest.TestCase):

    def test_core_consistency(self):
        system = load_pltg(CORE_PLTG)
        report = system.consistency()

        self.assertTrue(report.consistent, f"System inconsistent: {report}")
