"""py_structure and the py-ast effect: Python structure as values, read by Python's parser."""

import os
import tempfile
import unittest

from ..loader import LazyLoader
from ..py_structure import py_structure

SOURCE = '''
from enum import StrEnum
from dataclasses import dataclass

class Kind(StrEnum):
    """Kinds."""
    A = "a"
    B = "b"

    def label(self):
        return self.value

@dataclass
class Point:
    x: int
    y: int = 0
    origin = None

OPERATORS = {"+": 1, "-": 2}
KEYWORDS = (ALPHA, BETA, GAMMA)

def top():
    pass
'''


class TestPyStructure(unittest.TestCase):
    def test_each_query(self):
        self.assertEqual(py_structure(SOURCE, "members", "Kind"), ["A", "B"])
        self.assertEqual(py_structure(SOURCE, "methods", "Kind"), ["label"])
        self.assertEqual(py_structure(SOURCE, "fields", "Point"), ["x", "y"])
        self.assertEqual(py_structure(SOURCE, "classes"), ["Kind", "Point"])
        self.assertEqual(py_structure(SOURCE, "functions"), ["top"])
        self.assertEqual(py_structure(SOURCE, "keys", "OPERATORS"), ["'+'", "'-'"])
        self.assertEqual(py_structure(SOURCE, "items", "KEYWORDS"), ["ALPHA", "BETA", "GAMMA"])

    def test_a_name_the_source_does_not_define_is_refused(self):
        with self.assertRaises(ValueError):
            py_structure(SOURCE, "members", "Missing")
        with self.assertRaises(ValueError):
            py_structure(SOURCE, "keys", "KEYWORDS")
        with self.assertRaises(ValueError):
            py_structure(SOURCE, "lines")


class TestPyAstEffect(unittest.TestCase):
    def test_a_count_of_members_follows_the_source_and_is_typed(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "kinds.py"), "w") as f:
                f.write(SOURCE)
            with open(os.path.join(d, "main.pltg"), "w") as f:
                f.write(
                    '(load-document "kinds.py" "kinds.py")\n'
                    '(defterm kinds (py-ast "kinds.py" "members" "Kind")\n'
                    '    :evidence (evidence "kinds.py" :quotes ("class Kind(StrEnum):") :explanation "k"))\n'
                    "(derive misused (and kinds true) :using (kinds))\n"
                )
            system = LazyLoader().load_main(os.path.join(d, "main.pltg"))
        self.assertEqual(system.evaluate(system.engine.terms["kinds"].definition), ["A", "B"])
        typing = system.engine.dsl.typing
        self.assertEqual(str(typing.nodes["kinds"].type), "(List Str)")
        self.assertTrue(typing.errors.get("misused"))


if __name__ == "__main__":
    unittest.main()
