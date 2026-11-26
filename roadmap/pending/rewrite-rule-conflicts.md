# Rewrite Rule Conflicts

## Problem

A derive's rewrite rules are the axioms and theorems its `:using` lists. When two of them match the same expression and rewrite it differently, the first one tried applies and the other is ignored. Nothing in the consistency report says that two definitions of one head met in one derive:

```scheme
(fact a 3 :origin "...")
(defterm double :origin "...")
(axiom double-two   (= (double ?x) (* 2 ?x)) :origin "one world")
(axiom double-three (= (double ?x) (* 3 ?x)) :origin "another world")

(derive d (= (double a) 6) :using (a double-two double-three))   ; holds
(derive e (= (double a) 9) :using (a double-three double-two))   ; holds as well
```

Both theorems hold and the system reports itself consistent. Before the type-system branch fixed the order, the scope was a `set`: which rule applied followed Python's string hashing, so the same file proved a theorem under one `PYTHONHASHSEED` and refuted it under another. The order is now the listed one, which makes the outcome reproducible but still silent.

This is also what keeps rule scoping explicit. A term cannot bring its own rules into a derive (naming `linkage` would pull in every module's rules for `linkage`, transitively through their right-hand sides), because nothing would notice when the rules of two worlds meet.

## What we want

- Two rewrite rules in one derive's scope whose left-hand sides overlap, and whose right-hand sides differ once unified, are a load error naming the derive and both rules. The author chooses one world; the engine never chooses for them.
- Rules that do not overlap load as today: a base and a step case of different arity, disjoint shapes such as `((?...row))` and `((?...row) ?next ?...rows)`. `std/` and `validation/` load with no conflicts.
- Only once conflicts are refused: decide whether a term may bring the rules defined in its own module, so a derive naming `collapse` gets `std.epistemics`' rules for it while another module's rules for the same head stay explicit. A separate decision, not part of this task.

## Approach

Critical pairs, at the root. Rename the variables of two rules apart and unify their left-hand sides. If they do not unify, the rules never meet. If they do, apply the unifier to both right-hand sides: identical results are one rule restating another; different results are a conflict. The check needs no evaluation, and it is conservative: two different right-hand sides that would compute the same value are still reported, and the author keeps one.

- A unifier over patterns, splats included, next to `lang.match`, which matches a pattern against a ground expression only.
- The check runs where a derive's scope is built (`_collect_using_rules`), over that derive's own rules, so its cost follows the derive.
- Overlaps at a subterm position (a left-hand side matching inside another's) are the general confluence check; they can follow once root overlaps are in.

## Related

A theorem used as a source is valued by re-evaluating its formula with every rule in the system (`_build_restricted_env` calls `evaluate`), not the rules its own derive used. A theorem that held under the rules it listed can read as false where it is used, so one formula has two answers. Same family, separate fix.

## Files likely involved

- `parseltongue/core/lang.py`: pattern unification beside `match` and `substitute`
- `parseltongue/core/engines/engine_stack.py`, `parseltongue/core/engine.py`: the check in `_collect_using_rules`
- `parseltongue/core/tests/`: overlapping, disjoint and restating rules; std and `validation/` load clean
- `parseltongue/core/README.md`: the rule under `derive`
