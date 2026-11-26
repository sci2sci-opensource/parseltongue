# Type System — typed values, user-defined types, rule outcomes

## Problem

Every value is judged by Python truthiness, and that conflates three different things.

1. **A theorem and a computation.** `derive` treats any result except `False` or `None` as holding (`engine.py`, `does_not_hold = result is False or result is None`). A derive that evaluates to `5`, to `true`, or to the symbol `consistency-error` all count as theorems that hold. `bool` is a subclass of `int`, so `True == 1` as well.
2. **A rule that fired and a rule that was never tested.** `implies` is `(not a) or b`. An implication whose antecedent is false evaluates to `true`, and the derive holds. The engine's own self-proof contains such vacuous rules. `divergence-causes-error` (`validation/engine.pltg`) binds `?result-a` and `?result-b` to `divergence-evaluates-both` and `divergence-compares-results`, two facts that are both `true`, so its antecedent `(!= ?result-a ?result-b)` is `(!= true true)`: false. `value-divergence-causes-error` has the same shape. Both hold vacuously, and both are counted toward `hallucinated-is-error`.
3. **Counting existence and counting truth.** `count-exists` is `(if ?x 1 0)` per argument: it counts truthy values, so a count of things that exist, a count of rules that fired and a count of rules that were vacuous are the same number.

None of these is visible in the consistency report. The failure is silent by construction: the evaluator has no way to say "this is not a truth value" or "this rule was never exercised".

## What we want

Every node has a type known before evaluation, and a theorem is exactly a node of type `Bool` that evaluates to `true`. Applying a rule yields an outcome — fired, vacuous or violated — that is a value of its own type, not a boolean. Authors can define their own types, nominally, with evidence, so the domain's distinctions (a property of the code is not a value of a diff side) are checked by the language instead of by review.

## Approach

### Built-in types

`Bool`, `Num`, `Sym`, `Str`, `List[T]`, `Outcome`, and `Any` for host values (effects, documents) at an explicit boundary. A value of type `Any` is not usable as `Bool` without a typed coercion that is itself a node with a status. `Bool` and `Num` are disjoint: `true` is not `1`.

The epistemic status is **not** built in. It is the first user-defined type, in std (below), which keeps the core small and proves the mechanism on the language's own vocabulary.

### User-defined types

A new directive, `deftype`, introduces a named, nominal type. It is a node like any other: it carries `:evidence` or `:origin`, it has a status, and a derivation over an ungrounded type is a potential fabrication through the ordinary propagation.

- **Enumerations (closed sum types).** A finite, closed set of members, optionally ordered.

  ```scheme
  (deftype Status (one-of exemplifiable unknown hallucinated)
    :order (exemplifiable < unknown < hallucinated)
    :origin "the epistemic lattice; Russell's teapot closes it")
  ```

  Members are symbols of that type and nothing else. An ordered enumeration gets typed `max`/`min`/comparison, which is what `joint-status` and `collapse` compute today by hand.

- **Refinements.** A base type with a predicate over `?x`.

  ```scheme
  (deftype Count Num :where (and (integer? ?x) (>= ?x 0)))
  (deftype Probability Num :where (and (>= ?x 0) (<= ?x 1)))
  ```

  A refinement is a subtype of its base: a `Count` is usable where a `Num` is expected, not the other way round without a check. The predicate is checked when a value is produced; an SMT discharge (below) can check it statically later.

- **Nominal wrappers.** The same representation, a different meaning.

  ```scheme
  (deftype CodeProperty Bool :origin "a fact stating that the implementation does something")
  (deftype DiffSide Any :origin "the value one side of a diff resolves to")
  ```

  This is what the engine's self-proof needs: `divergence-evaluates-both` is a `CodeProperty`; binding it to `?result-a : DiffSide` in `error-on-diff-divergence` is a type error at load, before the vacuous outcome is ever computed. The same check catches `value-divergence-causes-error` binding `?value-b` to `value-divergence-no-downstream`, a different property than the one its name says.

- **Records (later).** Named fields with typed values, for structured facts. Not needed for the first cut; listed so the grammar leaves room for it.

Nodes take a type with `:type`: `(defterm correspondence :type Criterion …)`, `(fact divergence-evaluates-both true :type CodeProperty …)`. Without `:type`, a node's type is inferred.

### Inference and annotations

- A fact's type is inferred from its literal; a primitive term's is `Sym`; a `:type` annotation narrows either to a declared type.
- Every operator has a signature. `and`/`or`/`not`/`implies` are `Bool → Bool`; arithmetic is over `Num`; `=` and `!=` need both sides of one type; std functions carry signatures in std.
- An axiom is a typed schema: its `?vars` get types by unification with its uses, or from optional annotations, `(?ra Num)`, the same syntax a `forall` binder uses.
- A derive's type is inferred from its formula and its `:using`.

Annotations are optional: a `?var` the checker cannot type is `Any`, and the places where `Any` meets a typed position are reported, so the gaps are visible without forcing every file to be annotated first.

### Checking

A pass over the AST between parse and evaluation, owned by the loader. A mismatch — `(+ true 1)`, a `Status` used as a `Bool`, a `CodeProperty` bound to a `DiffSide` variable, a member of one enumeration compared to another's — is a new issue type, `TYPE_ERROR`, in the consistency report with the node, the position and both types. A type error does not stop the load: the file loads, the node is an issue, and everything derived from it is tainted by the existing propagation, exactly as unverified evidence is today.

### Judgements follow from types

- A derive of type `Bool` is a **theorem**: it holds when `true` and does not hold when `false`.
- A derive of any other type is a **computation**: a typed value with no truth claim. `criteria-count = 5` is a computation. Computations are not counted as theorems, and a report of "how many theorems hold" becomes exact.

### Rule outcomes

Applying an axiom rule — the existing `(derive <name> <axiom> :bind …)` form — has type `Outcome`: `fired` (the antecedent holds and the consequent holds), `vacuous` (the antecedent is false) or `violated` (the antecedent holds and the consequent does not). `implies` itself stays a `Bool` connective; the outcome belongs to the rule application.

```scheme
(derive divergence-causes-error error-on-diff-divergence
  :bind (...)
  :expect fired)        ; vacuous → error; without :expect, vacuous → warning, status unknown
```

A vacuous outcome without `:expect` is a new warning type, `VACUOUS_RULE`, with status unknown; with `:expect fired` it is an error. `violated` is always an error.

### Counting is typed

- `count-exists` counts names (`Any`): it stays the existence counter it is named for.
- `count-where` takes a predicate `(T → Bool)` and items of type `T`: `(count-where fired? r1 r2 r3)` counts rules that fired, and a vacuous rule is not one of them.

### Quantifying over closed types

An enumeration is finite and closed, so a `forall` over it is decidable by enumeration, with no solver:

```scheme
(deftype Criterion (one-of correspondence validity internal-consistency soundness limitations-visible) …)
(derive every-criterion-detected (forall ((?c Criterion)) (detected ?c)) :using (…))
```

A claim of the shape "every X has a Y" is then stated as what it is instead of as count arithmetic (`criteria − proven = 0`), and the type's evidence is what makes the set closed.

### Toward SMT discharge

The types are the sorts a solver needs: enumerations map to SMT datatypes, refinements to constraints, `Num` to `Int`/`Real`, records to datatypes. Symbolic theorems over non-finite types (`forall ((?ra Num))`) and a satisfiability check of a rule's antecedent — the principled form of vacuity detection — become a compile of the typed formula to SMT-LIB, not a second design. That is a separate task built on this one.

## Progress

Built on `feature/type-system`:

- Built-in types, gradual nominal typing, `deftype` (enumerations with `:order`, subset enumerations `(one-of … :of Parent)`, refinements with `:where` checked along their whole chain on facts and on derived values, wrappers), `:type`, `:types`, bindings checked against `:types`.
- Type expressions wherever a type is accepted: `(List T)` (covariant), `(-> A B R)` (contravariant parameters, covariant result), `(union A B)`, type variables `?T` unified at each call site, and `(Rest T)` as a function type's last parameter for variadic functions. Calls of function-typed terms are typed.
- Enumeration members are values carrying their enumeration and rank; `<`, `>`, `<=`, `>=` order two members of one enumeration by rank and refuse to order across enumerations. `=` keeps `Bool` and `Num` apart; `implies` returns a `Bool`.
- Rule outcomes (fired, vacuous, violated) and `:expect`; the `type_error` and `unmet_expectation` issues and the `vacuous_rule` warning; derives judged theorem (a `Bool` value) or computation.
- Typed std: `counting` (with `count-where`), `predicates`, `lists`, `compose`; `Status` and `Observation` are enumerations in `epistemics`.
- `py-ast`, a loader effect over a registered Python document: `(py-ast "engine.py" "members" "IssueType")` returns the names Python's parser finds (members, fields, methods, functions, classes, dict keys, tuple items), typed `(List Str)`, so a count derived from it follows the code.
- Typing is serialized with the system and restored with its enumerations' member values.

- A term with no declared type that heads rewrite rules has its signature inferred from them: each parameter's type is what its positions on the right-hand side demand, or a type variable when they demand none, and the result is the right-hand side's type; `(= (witness ?x) ?x)` infers `(-> ?x ?x)`. Rules of differing arity give a `Rest` signature.
- `+` is overloaded: numeric addition, or concatenation when every argument is a list.
- Records: `(Record :name Sym :value Num)`, structural in width and depth where written directly and nominal where declared; a record value is a keyword list `(:name revenue :value 3)`; `(get r :value)` is a core operator typed by the record's field.
- `outcome`, `fired?`, `vacuous?` and `violated?` read a rule application's outcome: `(count-where fired? (quote r1) (quote r2))` counts the rules that fired.
- `apply`, `pipe` and `filter` are typed; `apply` unifies through the function it applies.

Known limits: `pipe`'s type does not chain its functions' types (`(-> ?A (Rest (-> Any Any)) Any)`); restoring a system evaluates every term definition (`_rebuild_env`), so a term whose definition raises — such as a `get` of a field its record lacks — cannot be restored.

The corpus under the types:

- `validation/` loads with no type errors. String facts used as conditions became presence checks (`(!= doc "")`), a count used as a condition became `(> n 0)`, and bindings that bound one property to a variable naming another were rebound to facts quoting the property the variable names.
- Every rule application states its outcome. Rules whose antecedent the facts did not meet were rebound to a witnessing case quoted from the code (the run-on-entry gates, the consistency modes, the grounding defaults, written as the docstring's "no path outside verified/manual"); the engine's outcome rules conclude a `Channel`, an enumeration of the report's two channels, bound to facts quoting each append. The packaging breakage rules state `:expect vacuous`: their trigger is expected absent, and shipping a project without a file type it uses makes them fire and the expectation unmet.
- The self-proof's counts follow the code: the `IssueType` and `WarningType` members and the loader's effects are `py-ast` reads, and the error ↔ hallucinated, warning ↔ unknown isomorphism covers all of them — `absence_violated` and `obligation_violated` (which the proof had not covered), `type_error`, `unmet_expectation` and `vacuous_rule`, each with a witness, a rule and its channel. The README documents `deftype`, the types, the new issue, warning and effect rows, and `readme.pltg` follows it.

- Contamination no longer masks a value disagreement. A diff whose two values disagreed was filed as a `diff_contamination` warning when its downstream divergences all referenced sibling diffs (`value_divergent` required `d.empty`, and `diff_contamination_only` took the rest), so `a = 10` diffed against `b = 20` with a sibling diff on `a` reported the system consistent. The stale README counts reached that state during this work. Each diff now lands in exactly one class: a downstream divergence, a value divergence (values disagree, no real downstream divergence), or contamination (contamination only, values agree). The self-proof's contamination rule carries the third condition.

- A derive's formula names its sources, as its `:bind` values already did: the facts, terms and theorems it mentions need no `:using`. A rewrite rule is the exception: it applies only when `:using` lists it, so naming a term never brings in its rules, and two modules' rules for one head meet only in a derive that lists both. A derive tries its rules in the order it lists them; the scope was a `set`, so which of two matching rules applied followed the interpreter's string hashing, and one file could prove a theorem on one run and refute it on the next. Reporting two such rules in one scope is [its own task](../pending/rewrite-rule-conflicts.md).

- An axiom takes its own `:using`: the rules its right-hand side resolves with. A derive that lists the axiom gets them right after it, and theirs in turn, so a rule built on other rules is listed by its own name alone. Each hop is a rule its author named; nothing is found by a term's name.

## Decisions

- `?var` annotations are optional; untyped positions are `Any` and their boundaries are reported.
- Type errors are issues in the consistency report, not load failures.
- Types are nominal: two declared types with the same representation are distinct.
- The epistemic status moves into std as a `deftype`; it is no longer a set of untyped terms.

## Consequences

- Existing `.pltg` files will report type errors and vacuous rules — std, `validation/`, the demos and downstream projects. They are fixed in the files; nothing coerces or repairs a value to make it type-check.
- The engine's self-proof gains the new issue type and warning type in the same change: its error and warning type counts and their cross-checks in `validation/engine.pltg`, and the README's lists of issue and warning types. Its own vacuous rules (`divergence-causes-error`, `value-divergence-causes-error`) are remodelled to bind a witnessing case in which the two values differ, and a proof that rests on them reports `unknown` until they are.
- Evaluators besides the reference one must return typed values (keeping `Bool` and `Num` apart) and produce `Outcome` values for rule applications.

## Files likely involved

- `parseltongue/core/lang.py` — `deftype`, `:type`, `:expect`, `forall` binders
- a new `parseltongue/core/types.py` — the type representation, unification, the checking pass
- `parseltongue/core/loader/` — run the pass between parse and evaluation
- `parseltongue/core/engine.py` — typed evaluation, theorem vs computation, `Outcome`, `TYPE_ERROR`, `VACUOUS_RULE`
- `parseltongue/core/default_system_settings.py` — operator signatures
- `parseltongue/core/std/epistemics.pltg`, `counting.pltg` — `Status` as a `deftype`, `count-where`
- `parseltongue/core/validation/engine.pltg`, `README.md` — the new issue and warning types, the remodelled rules
