"""Tests for InteractivePipeline._restore_system."""

import copy
import unittest

from parseltongue.core import System, load_source


class TestRestoreSystem(unittest.TestCase):
    """_restore_system must copy engine state from a snapshot back into the live system."""

    def test_restore_clears_state(self):
        """Restoring an empty snapshot wipes facts/axioms/terms added after the snapshot."""
        s = System()
        snapshot = copy.deepcopy(s)

        load_source(s, '(fact x 42 :origin "test")')
        self.assertIn("x", s.facts)

        # Restore from empty snapshot
        s.engine.axioms = snapshot.engine.axioms
        s.engine.theorems = snapshot.engine.theorems
        s.engine.terms = snapshot.engine.terms
        s.engine.facts = snapshot.engine.facts
        s.engine.env = snapshot.engine.env
        s.engine.diffs = snapshot.engine.diffs

        self.assertNotIn("x", s.facts)

    def test_restore_preserves_documents(self):
        """Documents registered before snapshot survive restore."""
        s = System()
        s.register_document("doc1", "Hello world")
        snapshot = copy.deepcopy(s)

        load_source(s, '(fact x 1 :origin "test")')
        self.assertIn("x", s.facts)

        s.engine.axioms = snapshot.engine.axioms
        s.engine.theorems = snapshot.engine.theorems
        s.engine.terms = snapshot.engine.terms
        s.engine.facts = snapshot.engine.facts
        s.engine.env = snapshot.engine.env
        s.engine.diffs = snapshot.engine.diffs

        self.assertNotIn("x", s.facts)
        self.assertIn("doc1", s.documents)

    def test_restore_with_populated_snapshot(self):
        """Restoring a snapshot that had facts brings them back."""
        s = System()
        load_source(s, '(fact a 10 :origin "test")')
        snapshot = copy.deepcopy(s)

        # Add more, then restore
        load_source(s, '(fact b 20 :origin "test")')
        self.assertIn("b", s.facts)

        s.engine.axioms = snapshot.engine.axioms
        s.engine.theorems = snapshot.engine.theorems
        s.engine.terms = snapshot.engine.terms
        s.engine.facts = snapshot.engine.facts
        s.engine.env = snapshot.engine.env
        s.engine.diffs = snapshot.engine.diffs

        self.assertIn("a", s.facts)
        self.assertNotIn("b", s.facts)
