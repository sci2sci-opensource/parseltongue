"""Types: deftype, :type, :types, rule outcomes, and what the consistency report says of them."""

import unittest

from parseltongue import Symbol, System, load_source

from ..engine import IssueType, WarningType


def _system(source: str) -> System:
    s = System()
    load_source(s, source)
    return s


def _errors(s: System, name: str) -> list[str]:
    return s.engine.dsl.typing.errors.get(name, [])


def _report_names(s: System, kind) -> set[str]:
    report = s.consistency()
    groups = [g for g in report.issues + report.warnings if g.type == kind]
    names = set()
    for g in groups:
        for item in g.items:
            names.add(item[0] if isinstance(item, tuple) else item)
    return names


RULE = """
(defterm divergence :origin "the state a divergence produces")
(deftype DiffSide Any :origin "the value one side of a diff resolves to")
(deftype CodeProperty Bool :origin "a fact stating what the implementation does")
(axiom diverges
    (implies (!= ?a ?b) (= divergence divergence))
    :types ((?a DiffSide) (?b DiffSide))
    :origin "two sides that differ diverge")
"""


class TestJudgements(unittest.TestCase):
    def test_a_bool_derive_is_a_theorem_and_any_other_value_a_computation(self):
        s = _system('(fact n 5 :origin "n") (derive more (+ n 1) :using (n)) (derive positive (> n 0) :using (n))')
        judgements = s.engine.dsl.typing.judgements
        self.assertEqual(judgements["more"], "computation")
        self.assertEqual(judgements["positive"], "theorem")

    def test_true_is_not_one(self):
        s = _system("(derive same (= true 1) :using ())")
        self.assertIs(s.evaluate(s.engine.theorems["same"].wff), False)
        self.assertTrue(_errors(s, "same"))


class TestRuleOutcomes(unittest.TestCase):
    def test_a_rule_whose_antecedent_is_false_is_vacuous_and_a_warning(self):
        s = _system(
            RULE + '(fact x 1 :origin "x") (derive same-sides diverges :bind ((?a x) (?b x)) :using (diverges x))'
        )
        self.assertEqual(s.engine.dsl.typing.outcomes["same-sides"], "vacuous")
        self.assertIn("same-sides", _report_names(s, WarningType.VACUOUS_RULE))

    def test_a_rule_whose_antecedent_holds_fired(self):
        s = _system(
            RULE + '(fact x 1 :origin "x") (fact y 2 :origin "y")'
            "(derive differ diverges :bind ((?a x) (?b y)) :using (diverges x y) :expect fired)"
        )
        self.assertEqual(s.engine.dsl.typing.outcomes["differ"], "fired")
        self.assertNotIn("differ", _report_names(s, IssueType.UNMET_EXPECTATION))

    def test_an_expected_outcome_that_does_not_happen_is_an_issue(self):
        s = _system(
            RULE + '(fact x 1 :origin "x")'
            "(derive same-sides diverges :bind ((?a x) (?b x)) :using (diverges x) :expect fired)"
        )
        self.assertIn("same-sides", _report_names(s, IssueType.UNMET_EXPECTATION))
        self.assertNotIn("same-sides", _report_names(s, WarningType.VACUOUS_RULE))


class TestNominalTypes(unittest.TestCase):
    def test_a_declared_type_is_not_assignable_to_another_with_the_same_representation(self):
        s = _system(
            RULE + '(fact evaluates-both true :type CodeProperty :origin "code")'
            "(derive d diverges :bind ((?a evaluates-both) (?b evaluates-both)) :using (diverges evaluates-both))"
        )
        self.assertTrue(any("CodeProperty" in e for e in _errors(s, "d")))

    def test_an_untyped_value_is_admitted_by_a_declared_type_of_its_representation(self):
        s = _system(RULE + '(fact x 1 :origin "x") (derive d diverges :bind ((?a x) (?b x)) :using (diverges x))')
        self.assertEqual(_errors(s, "d"), [])

    def test_a_proposition_must_be_bool(self):
        s = _system(
            '(defterm state :origin "a symbol") (fact p true :origin "p") (derive d (and p state) :using (p state))'
        )
        self.assertTrue(any("state is Sym" in e for e in _errors(s, "d")))


class TestDeftype(unittest.TestCase):
    def test_enumeration_members_are_typed_and_others_refused(self):
        s = _system(
            '(deftype Severity (one-of note warning error) :order (note < warning < error) :origin "severities")'
            '(fact level warning :type Severity :origin "l") (fact other fatal :type Severity :origin "o")'
        )
        typing = s.engine.dsl.typing
        self.assertEqual(typing.types["Severity"].order, ("note", "warning", "error"))
        self.assertEqual(str(typing.nodes["level"].type), "Severity")
        self.assertEqual(_errors(s, "level"), [])
        self.assertTrue(_errors(s, "other"))

    def test_a_refinement_checks_its_predicate(self):
        s = _system(
            '(deftype Count Num :where (>= ?x 0) :origin "a count")'
            '(fact good 3 :type Count :origin "g") (fact bad -1 :type Count :origin "b")'
        )
        self.assertEqual(_errors(s, "good"), [])
        self.assertTrue(_errors(s, "bad"))

    def test_a_refinement_of_a_refinement_checks_every_predicate_on_its_chain(self):
        s = _system(
            '(deftype Count Num :where (>= ?x 0) :origin "a count")'
            '(deftype Percent Count :where (<= ?x 100) :origin "a percentage")'
            '(fact over 140 :type Percent :origin "o") (fact neg -3 :type Percent :origin "n")'
            '(fact n 7 :type Count :origin "n") (derive as-percent n :type Percent :using (n))'
        )
        self.assertTrue(any("Percent" in e for e in _errors(s, "over")))
        self.assertTrue(any("Count" in e for e in _errors(s, "neg")))
        self.assertEqual(_errors(s, "as-percent"), [])

    def test_a_derived_value_is_checked_against_its_declared_refinement(self):
        s = _system(
            '(deftype Percent Num :where (<= ?x 100) :origin "a percentage")'
            '(fact share 40 :type Percent :origin "s") (derive grown (+ share 100) :type Percent :using (share))'
        )
        self.assertTrue(any("Percent" in e for e in _errors(s, "grown")))

    def test_an_ordered_enumeration_refines_by_rank(self):
        s = _system(
            '(deftype Severity (one-of note warning error) :order (note < warning < error) :origin "severities")'
            '(deftype Serious Severity :where (>= ?x warning) :origin "warning or worse")'
            '(fact quiet note :type Serious :origin "q") (fact loud error :type Serious :origin "l")'
        )
        self.assertTrue(_errors(s, "quiet"))
        self.assertEqual(_errors(s, "loud"), [])

    def test_members_of_different_enumerations_do_not_order(self):
        s = _system(
            '(deftype Severity (one-of note error) :order (note < error) :origin "s")'
            '(deftype Size (one-of small large) :order (small < large) :origin "z")'
        )
        self.assertIs(s.evaluate([Symbol("<"), Symbol("note"), Symbol("error")]), True)
        with self.assertRaises(TypeError):
            s.evaluate([Symbol("<"), Symbol("note"), Symbol("large")])

    def test_a_type_is_a_node_carrying_its_evidence(self):
        s = _system('(deftype Count Num :where (>= ?x 0) :origin "a count")')
        self.assertIn("Count", s.engine.terms)
        self.assertIn("Count", _report_names(s, IssueType.NO_EVIDENCE))

    def test_an_unknown_type_is_an_error(self):
        s = _system('(fact x 1 :type Nothing :origin "x")')
        self.assertTrue(any("names no type" in e for e in _errors(s, "x")))

    def test_retract_forgets_a_nodes_type(self):
        s = _system('(fact x 1 :origin "x")')
        s.retract("x")
        self.assertNotIn("x", s.engine.dsl.typing.nodes)

    def test_a_copy_keeps_the_types_and_owns_its_own(self):
        s = _system('(deftype Count Num :origin "a count") (fact x 1 :type Count :origin "x")')
        clone = s.copy()
        self.assertEqual(str(clone.engine.dsl.typing.nodes["x"].type), "Count")
        load_source(clone, '(fact y 2 :origin "y")')
        self.assertNotIn("y", s.engine.dsl.typing.nodes)


class TestTypeExpressions(unittest.TestCase):
    def test_a_list_type_is_covariant_in_its_element(self):
        s = _system(
            '(deftype Count Num :where (>= ?x 0) :origin "c")'
            '(defterm total :type (-> (List Num) Num) :origin "sums a list")'
            '(defterm flags :type (List Bool) :origin "f") (defterm counts :type (List Count) :origin "c")'
            "(derive ok (total counts) :using (total counts)) (derive bad (total flags) :using (total flags))"
        )
        self.assertEqual(_errors(s, "ok"), [])
        self.assertTrue(_errors(s, "bad"))

    def test_a_polymorphic_function_unifies_its_type_variable_across_arguments(self):
        s = _system(
            '(defterm pick :type (-> Bool ?T ?T ?T) :origin "if, as a function")'
            '(fact n 1 :origin "n") (fact m 2 :origin "m") (fact b true :origin "b")'
            "(derive same (pick b n m) :using (pick b n m))"
            "(derive mixed (pick b n b) :using (pick b n))"
            "(derive sum (= (pick b n m) 1) :using (pick b n m))"
        )
        self.assertEqual(_errors(s, "same"), [])
        self.assertEqual(_errors(s, "sum"), [])
        self.assertEqual(str(s.engine.dsl.typing.nodes["same"].type), "Num")
        self.assertTrue(_errors(s, "mixed"))

    def test_a_variadic_function_types_every_rest_argument(self):
        s = _system(
            '(defterm count-true :type (-> (Rest Bool) Num) :origin "counts trues")'
            '(fact p true :origin "p") (fact q false :origin "q") (fact n 3 :origin "n")'
            "(derive ok (count-true p q p) :using (count-true p q))"
            "(derive bad (count-true p n) :using (count-true p n))"
        )
        self.assertEqual(_errors(s, "ok"), [])
        self.assertTrue(any("n is Num" in e for e in _errors(s, "bad")))

    def test_an_arity_mismatch_is_an_error(self):
        s = _system('(defterm f :type (-> Num Num) :origin "f") (derive d (f 1 2) :using (f))')
        self.assertTrue(any("argument" in e for e in _errors(s, "d")))

    def test_a_union_admits_each_of_its_members(self):
        s = _system(
            '(deftype Key (union Sym Num) :origin "a key")'
            '(fact by-name alpha :type Key :origin "k") (fact by-index 3 :type Key :origin "k")'
            '(fact by-flag true :type Key :origin "k")'
        )
        self.assertEqual(_errors(s, "by-name"), [])
        self.assertEqual(_errors(s, "by-index"), [])
        self.assertTrue(_errors(s, "by-flag"))

    def test_a_function_type_is_contravariant_in_its_parameters(self):
        s = _system(
            '(deftype Count Num :where (>= ?x 0) :origin "c")'
            '(defterm apply-to-count :type (-> (-> Count Bool) Bool) :origin "a")'
            '(defterm on-num :type (-> Num Bool) :origin "n") (defterm on-bool :type (-> Bool Bool) :origin "b")'
            "(derive ok (apply-to-count on-num) :using (apply-to-count on-num))"
            "(derive bad (apply-to-count on-bool) :using (apply-to-count on-bool))"
        )
        self.assertEqual(_errors(s, "ok"), [])
        self.assertTrue(_errors(s, "bad"))

    def test_rest_is_only_a_last_parameter(self):
        s = _system('(defterm f :type (-> (Rest Num) Bool Num) :origin "f")')
        self.assertTrue(any("Rest" in e for e in _errors(s, "f")))


class TestSubsetEnumerations(unittest.TestCase):
    SOURCE = (
        '(deftype Severity (one-of note warning error) :order (note < warning < error) :origin "s")'
        '(deftype Serious (one-of warning error :of Severity) :origin "warning or worse")'
    )

    def test_a_subset_admits_its_members_and_refuses_the_rest(self):
        s = _system(self.SOURCE + '(fact a error :type Serious :origin "a") (fact b note :type Serious :origin "b")')
        self.assertEqual(_errors(s, "a"), [])
        self.assertTrue(_errors(s, "b"))

    def test_a_subset_is_a_subtype_of_its_enumeration_and_keeps_its_order(self):
        s = _system(
            self.SOURCE
            + '(fact a error :type Serious :origin "a") (defterm level :type (-> Severity Bool) :origin "l")'
            "(derive ok (level a) :using (level a)) (derive louder (> a warning) :using (a warning))"
        )
        self.assertEqual(_errors(s, "ok"), [])
        self.assertIs(s.evaluate(s.engine.theorems["louder"].wff), True)

    def test_a_subset_names_only_members_of_its_enumeration(self):
        s = _system(self.SOURCE + '(deftype Odd (one-of warning fatal :of Severity) :origin "o")')
        self.assertTrue(any("fatal" in e for e in _errors(s, "Odd")))


class TestSerialization(unittest.TestCase):
    def test_typing_survives_a_round_trip(self):
        s = _system(
            '(deftype Severity (one-of note error) :order (note < error) :origin "s")'
            '(deftype Count Num :where (>= ?x 0) :origin "c")'
            '(defterm total :type (-> (Rest Count) Count) :origin "t")'
            '(fact level error :type Severity :origin "l") (fact bad -1 :type Count :origin "b")'
        )
        restored = System.from_dict(s.to_dict())
        typing = restored.engine.dsl.typing
        self.assertEqual(typing.types["Count"].where, s.engine.dsl.typing.types["Count"].where)
        self.assertEqual(str(typing.nodes["total"].type), "(-> (Rest Count) Count)")
        self.assertEqual(typing.errors, s.engine.dsl.typing.errors)
        self.assertIs(restored.evaluate([Symbol("<"), Symbol("note"), Symbol("error")]), True)
        self.assertEqual(restored.consistency().to_dict(), s.consistency().to_dict())


if __name__ == "__main__":
    unittest.main()
