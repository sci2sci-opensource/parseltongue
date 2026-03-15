"""
Parseltongue System — composes Engine with defaults, serialization, and introspection.
"""

import logging
from typing import Callable, Self

from .atoms import SILENCE, Evidence, Symbol
from .default_system_settings import DEFAULT_OPERATORS, ENGINE_DOCS
from .engine import Engine, Fact
from .engine import load_source as _engine_load_source
from .lang import (
    DSL_KEYWORDS,
    LANG_DOCS,
    Axiom,
    Interpreter,
    PGStringParser,
    Rewriter,
    Sentence,
    Term,
    Theorem,
    to_sexp,
)
from .serialization import (
    deserialize_axiom,
    deserialize_fact,
    deserialize_term,
    deserialize_theorem,
    serialize_axiom,
    serialize_fact,
    serialize_term,
    serialize_theorem,
)

log = logging.getLogger("parseltongue")


class AbstractSystem(Rewriter, Interpreter):
    """Composes Engine with serialization and introspection. All args required — no defaults."""

    def __init__(
        self,
        initial_env: dict,
        docs: dict,
        overridable: bool,
        strict_derive: bool,
        effects: dict[str, Callable],
        verifier,
        name: str | None = None,
    ):
        env: dict = {}
        env.update(initial_env)

        self.engine = Engine(env, overridable=overridable, strict_derive=strict_derive, verifier=verifier, name=name)
        self._docs = docs

        for name, fn in effects.items():
            self.engine.env[Symbol(name)] = lambda *args, _fn=fn: _fn(self, *args)

    @property
    def facts(self):
        return self.engine.facts

    @property
    def axioms(self):
        return self.engine.axioms

    @property
    def theorems(self):
        return self.engine.theorems

    @property
    def terms(self):
        return self.engine.terms

    @property
    def diffs(self):
        return self.engine.diffs

    @property
    def documents(self):
        return self.engine.documents

    def evaluate(self, expr: Sentence, local_env=None) -> Sentence:
        return self.engine.evaluate(expr, local_env)

    def interpret(self, source: str) -> tuple["AbstractSystem", Sentence]:
        _engine_load_source(self.engine, source)
        result = PGStringParser.translate(source)
        if isinstance(result, (list, tuple)) and result and isinstance(result[0], (list, tuple)):
            exprs = result
        else:
            exprs = [result] if result else []
        if not exprs:
            return (self, SILENCE)
        last = exprs[-1]
        if isinstance(last, (list, tuple)) and last and last[0] in DSL_KEYWORDS:
            return (self, SILENCE)
        return (self, self.engine.evaluate(last))

    def set_fact(self, name, value, origin):
        self.engine.set_fact(name, value, origin)

    def verify_manual(self, name):
        self.engine.verify_manual(name)

    def register_document(self, name, text):
        self.engine.register_document(name, text)

    def load_document(self, name, path):
        self.engine.load_document(name, path)

    def introduce_axiom(self, name, wff, origin):
        return self.engine.introduce_axiom(name, wff, origin)

    def introduce_term(self, name, definition, origin):
        return self.engine.introduce_term(name, definition, origin)

    def derive(self, name, wff, using):
        return self.engine.derive(name, wff, using)

    def instantiate(self, name, bindings):
        return self.engine.instantiate(name, bindings)

    def retract(self, name):
        self.engine.retract(name)

    def register_diff(self, name, replace, with_):
        self.engine.register_diff(name, replace, with_)

    def eval_diff(self, name):
        return self.engine.eval_diff(name)

    def rederive(self, name):
        self.engine.rederive(name)

    def consistency(self):
        return self.engine.consistency()

    # ----------------------------------------------------------
    # Introspection
    # ----------------------------------------------------------

    def _format_origin(self, origin) -> dict | str:
        if isinstance(origin, Evidence):
            result = {
                "document": origin.document,
                "quotes": origin.quotes,
                "explanation": origin.explanation,
                "verified": origin.verified,
                "verify_manual": origin.verify_manual,
                "grounded": origin.is_grounded,
            }
            if origin.verification:
                result["verification"] = origin.verification
            return result
        return origin

    def provenance(self, name: str) -> dict:
        if name in self.engine.facts:
            return {
                "name": name,
                "type": "fact",
                "origin": self._format_origin(self.engine.facts[name].origin),
            }

        if name in self.engine.axioms:
            ax = self.engine.axioms[name]
            return {
                "name": name,
                "type": "axiom",
                "wff": to_sexp(ax.wff),
                "origin": self._format_origin(ax.origin),
            }

        if name in self.engine.terms:
            term = self.engine.terms[name]
            defn = to_sexp(term.definition) if term.definition is not None else "(forward declaration)"
            return {
                "name": name,
                "type": "term",
                "definition": defn,
                "origin": self._format_origin(term.origin),
            }

        if name in self.engine.theorems:
            thm = self.engine.theorems[name]
            return {
                "name": name,
                "type": "theorem",
                "wff": to_sexp(thm.wff),
                "origin": self._format_origin(thm.origin),
                "derivation_chain": [self.provenance(dep) for dep in thm.derivation],
            }

        if name in self.engine.diffs:
            diff = self.engine.diffs[name]
            result = self.engine.eval_diff(name)
            return {
                "name": name,
                "type": "diff",
                "replace": diff["replace"],
                "with": diff["with"],
                "value_a": result.value_a,
                "value_b": result.value_b,
                "divergences": result.divergences,
                "provenance_a": self.provenance(diff["replace"]),
                "provenance_b": self.provenance(diff["with"]),
            }

        raise KeyError(f"Unknown: {name}")

    def list_axioms(self) -> list[Axiom]:
        result = list(self.engine.axioms.values())
        for ax in result:
            log.info("%s", ax)
        return result

    def list_theorems(self) -> list[Theorem]:
        result = list(self.engine.theorems.values())
        for thm in result:
            log.info("%s", thm)
        return result

    def list_terms(self) -> list[Term]:
        result = list(self.engine.terms.values())
        for term in result:
            log.info("%s", term)
        return result

    def list_facts(self) -> list[Fact]:
        result = list(self.engine.facts.values())
        for fact in result:
            log.info("%s", fact)
        return result

    # ----------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize system state: terms, facts, axioms, theorems, verifier index."""
        return {
            "terms": {n: serialize_term(t) for n, t in self.engine.terms.items()},
            "facts": {n: serialize_fact(f) for n, f in self.engine.facts.items()},
            "axioms": {n: serialize_axiom(a) for n, a in self.engine.axioms.items()},
            "theorems": {n: serialize_theorem(t) for n, t in self.engine.theorems.items()},
            "diffs": dict(self.engine.diffs),
            "documents": dict(self.engine.documents),
            "verifier_index": self.engine._verifier.index.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> Self:
        from .quote_verifier import QuoteVerifier
        from .quote_verifier.index import DocumentIndex

        documents = data.get("documents", {})

        # Restore verifier with pre-built index if available
        verifier = None
        if "verifier_index" in data:
            index = DocumentIndex.from_dict(data["verifier_index"], documents)
            verifier = QuoteVerifier()
            verifier.set_index(index)

        system = cls(verifier=verifier, **kwargs)
        system.engine.terms = {n: deserialize_term(n, d) for n, d in data.get("terms", {}).items()}
        system.engine.facts = {n: deserialize_fact(n, d) for n, d in data.get("facts", {}).items()}
        system.engine.axioms = {n: deserialize_axiom(n, d) for n, d in data.get("axioms", {}).items()}
        system.engine.theorems = {n: deserialize_theorem(n, d) for n, d in data.get("theorems", {}).items()}
        for name, diff in data.get("diffs", {}).items():
            system.engine.register_diff(name, diff["replace"], diff["with"])
        for name, text in documents.items():
            system.engine.register_document(name, text)
        system._rebuild_env()
        return system

    def _rebuild_env(self) -> None:
        from .lang import EQ

        for name, fact in self.engine.facts.items():
            self.engine.env[Symbol(name)] = fact.wff

        for _name, axiom in self.engine.axioms.items():
            wff = axiom.wff
            if isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ and isinstance(wff[1], Symbol):
                try:
                    self.engine.env[wff[1]] = self.engine.evaluate(wff[2])
                except (NameError, TypeError):
                    pass

        remaining = {n for n, t in self.engine.terms.items() if t.definition is not None}
        for _ in range(len(remaining) + 1):
            progress = False
            for name in list(remaining):
                try:
                    defn = self.engine.terms[name].definition
                    assert defn is not None  # filtered by remaining set
                    val = self.engine.evaluate(defn)
                    self.engine.env[Symbol(name)] = val
                    remaining.discard(name)
                    progress = True
                except (NameError, TypeError):
                    pass
            if not remaining or not progress:
                break

    # ----------------------------------------------------------
    # Display
    # ----------------------------------------------------------

    def doc(self) -> str:
        all_docs = {**LANG_DOCS, **self._docs}
        lines = ["Parseltongue System Documentation", "=" * 40]

        categories: dict[str, list] = {}
        documented = set()
        for sym in self.engine.env:
            if isinstance(sym, Symbol) and sym in all_docs:
                d = all_docs[sym]
                categories.setdefault(d["category"], []).append((sym, d))
                documented.add(sym)

        for sym, d in all_docs.items():
            if sym not in documented and d["category"] in ("special", "directive", "structural", "keyword"):
                categories.setdefault(d["category"], []).append((sym, d))
                documented.add(sym)

        order = ["special", "arithmetic", "comparison", "logic", "directive", "structural", "keyword"]
        titles = {
            "special": "Special Forms",
            "arithmetic": "Arithmetic Operators",
            "comparison": "Comparison Operators",
            "logic": "Logic Operators",
            "directive": "DSL Directives",
            "structural": "Structural",
            "keyword": "Keyword Arguments",
        }
        all_cats = order + [c for c in categories if c not in order]

        for cat in all_cats:
            entries = categories.get(cat, [])
            if not entries:
                continue
            title = titles.get(cat, cat.replace("_", " ").title())
            lines += ["", f"  {title}", f"  {'-' * len(title)}"]
            for sym, d in entries:
                lines.append(f"    {sym}")
                lines.append(f"      {d['description'].split(chr(10))[0]}")
                lines.append(f"      Example: {d['example']}")
                if "expected" in d:
                    lines.append(f"      => {d['expected']}")
                if "patterns" in d:
                    lines.append("      Patterns:")
                    for pattern in d["patterns"]:
                        for pline in pattern.split("\n"):
                            lines.append(f"        {pline}")
                        lines.append("")

        return "\n".join(lines)

    def state(self) -> str:
        lines = []
        if self.engine.facts:
            lines += ["  Facts", "  -----"]
            lines += [f"    {n} = {f.wff}" for n, f in self.engine.facts.items()]
        if self.engine.terms:
            lines += ["", "  Terms", "  -----"]
            for n, t in self.engine.terms.items():
                defn = to_sexp(t.definition) if t.definition is not None else "(forward declaration)"
                lines.append(f"    {n} := {defn}")
        if self.engine.axioms:
            lines += ["", "  Axioms", "  ------"]
            lines += [f"    {n}: {to_sexp(a.wff)}" for n, a in self.engine.axioms.items()]
        if self.engine.theorems:
            lines += ["", "  Theorems", "  --------"]
            for n, thm in self.engine.theorems.items():
                lines.append(f"    {n}: {to_sexp(thm.wff)}  [from: {', '.join(thm.derivation)}]")
        if self.engine.diffs:
            lines += ["", "  Diffs", "  -----"]
            lines += [f"    {n}: {p['replace']} vs {p['with']}" for n, p in self.engine.diffs.items()]
        return "\n".join(lines) if lines else "  (empty)"

    def __repr__(self):
        e = self.engine
        return (
            f"System[{e.name}]({len(e.axioms)} axioms, "
            f"{len(e.theorems)} theorems, "
            f"{len(e.terms)} terms, "
            f"{len(e.facts)} facts, "
            f"{len(e.diffs)} diffs, "
            f"{len(e.documents)} docs)"
        )


class DefaultSystem(AbstractSystem):
    """System with default operators and docs. The standard entry point."""

    def __init__(
        self,
        overridable: bool = False,
        initial_env: dict | None = None,
        docs: dict | None = None,
        strict_derive: bool = True,
        effects: dict[str, Callable] | None = None,
        verifier=None,
        name: str | None = None,
    ):
        super().__init__(
            initial_env=initial_env if initial_env is not None else DEFAULT_OPERATORS,
            docs=docs if docs is not None else ENGINE_DOCS,
            overridable=overridable,
            strict_derive=strict_derive,
            effects=effects or {},
            verifier=verifier,
            name=name,
        )


class EmptySystem(AbstractSystem):
    """System with no operators — a blank slate."""

    def __init__(
        self,
        overridable: bool = False,
        initial_env: dict | None = None,
        docs: dict | None = None,
        strict_derive: bool = True,
        effects: dict[str, Callable] | None = None,
        verifier=None,
        name: str | None = None,
    ):
        super().__init__(
            initial_env=initial_env if initial_env is not None else {},
            docs=docs if docs is not None else {},
            overridable=overridable,
            strict_derive=strict_derive,
            effects=effects or {},
            verifier=verifier,
            name=name,
        )


# Backward-compatible alias — System() gives DefaultSystem
System = DefaultSystem


def load_source(system: AbstractSystem, source: str):
    _engine_load_source(system.engine, source)
