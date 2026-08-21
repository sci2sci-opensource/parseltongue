"""
Parseltongue Engine — evaluation core.

Accepts an env dict and provides: evaluation, rewriting, derivation,
diffs, consistency checking, document management (direct registration,
loading from files, and ground-truth indexing for evidence verification),
evidence verification, and DSL loading.

TODO: Engine uses isinstance(x, (list, tuple)) throughout as a mechanical
fix for grammar returning tuples. Should instantiate lang-level rewriters
(match/substitute/free_vars) properly instead of duck-typing both containers.
"""

import logging
from dataclasses import replace
from typing import Callable, TypeVar

from ..atoms import SILENCE, WFF, Evidence, Silence, Symbol
from ..dsl_loader import DslLoader
from ..engine import (
    ConsistencyIssue,
    ConsistencyReport,
    ConsistencyWarning,
    DiffResult,
    Fact,
    IssueType,
    WarningType,
    _confounded_quote_pairs,
    _corpus_counter_examples,
    _corpus_polarity,
    _corpus_reasons,
    _evidence_quote_provenance,
    reverify_evidence,
)
from ..engine import Engine as EngineProtocol
from ..lang import (
    DELEGATE,
    EQ,
    EVIDENCE_TYPE_CORPUS_QUERY,
    EVIDENCE_TYPE_DOC_QUOTE,
    IF,
    KW_BIND,
    LET,
    PROJECT,
    QUOTE,
    SCOPE,
    SELF,
    SPECIAL_FORMS,
    STRICT,
    Axiom,
    PGStringParser,
    Sentence,
    Term,
    Theorem,
    free_vars,
    get_keyword,
    match,
    substitute,
    to_sexp,
)
from ..quote_verifier import QuoteVerifier
from ..quote_verifier.evidence_verifiers import DocQuoteEvidenceVerifier, DocumentCorpusVerifier, EvidenceVerifier

log = logging.getLogger("parseltongue")

# Store value types that verify_manual can re-sign in place.
_SignableT = TypeVar("_SignableT", Fact, Axiom, Theorem, Term)

_TAIL_CALL = object()  # sentinel for iterative eval tail-call signaling
_MISSING = object()  # sentinel for trail: key didn't exist before

# -- Continuation tags for iterative _eval (ints for speed) --
_K_ARGS = 0  # evaluating argument list
_K_IF_COND = 1  # waiting for if-condition
_K_LET_BIND = 2  # waiting for let-binding value
_K_BIND_PAIR = 3  # waiting for :bind pair value
_K_SELF_ARGS = 4  # evaluating (self ...) args sequentially
_K_HEAD = 5  # waiting for head evaluation (rare: compound heads only)
_K_STRICT_ARG = 6  # waiting for (strict ...) arg in lazy path
_K_PROJECT_BASIS = 7  # waiting for project basis
_K_TRAIL_UNDO = 8  # env restore point — undo trail on scope exit
_K_CONTEXT = 9  # context marker for observer (name,) — popped after body eval


# ============================================================
# Consistency classification
# ============================================================


# ============================================================
# Engine
# ============================================================


class Engine(EngineProtocol):
    """Evaluation engine with document management. No serialization."""

    def __init__(
        self,
        env: dict,
        overridable: bool = False,
        strict_derive: bool = True,
        verifier: QuoteVerifier | None = None,
        name: str | None = None,
        max_eval_depth: int = 10_000,
        evidence_verifiers: "dict[str, EvidenceVerifier] | None" = None,
        dsl_loader_cls: "type[DslLoader]" = DslLoader,
    ):
        self.name: str = name or self._infer_name()
        self.dsl = dsl_loader_cls(self)
        self.axioms: dict[str, Axiom] = {}
        self.theorems: dict[str, Theorem] = {}
        self.terms: dict[str, Term] = {}
        self.facts: dict[str, Fact] = {}
        self.env: dict = dict(env)
        self.diffs: dict[str, dict] = {}
        self.diff_refs: dict[str, set[str]] = {}  # name → diff names that reference it
        self.documents: dict[str, str] = {}
        self._entity_aliases: dict[str, str] = {}
        self._verifier = verifier or QuoteVerifier()
        self._evidence_verifiers: dict[str, EvidenceVerifier] = {
            EVIDENCE_TYPE_DOC_QUOTE: DocQuoteEvidenceVerifier(self._verifier, self.documents),
            EVIDENCE_TYPE_CORPUS_QUERY: DocumentCorpusVerifier(self._verifier.index),
        }
        if evidence_verifiers:
            self._evidence_verifiers.update(evidence_verifiers)
        self.overridable = overridable
        self.strict_derive = strict_derive
        self.max_eval_depth = max_eval_depth
        self._eval_observer = None  # callable(expr, result, stack) or None
        # ── Tracing (off by default, activated by Tracer) ──
        self._tracing: bool = False
        self._trace_log: list = []  # completed context traces (appended on _K_CONTEXT pop)
        self._trace_context: str | None = None  # current context name (for _rewrite)
        self._trace_current: list | None = None  # current context's trace list (for _rewrite)
        self._tracer_stack: list = []  # [(name, traces_list), ...] — mirrors _K_CONTEXT frames
        import sys

        if sys.getrecursionlimit() < max_eval_depth:
            sys.setrecursionlimit(max_eval_depth)

    @staticmethod
    def _infer_name() -> str:
        """Infer engine name from instantiation site."""
        import inspect

        for frame in inspect.stack()[2:]:  # skip _infer_name + __init__
            module = frame.filename.rsplit("/", 1)[-1].removesuffix(".py")
            # Skip generic infrastructure — find the real caller
            if module not in ("system", "engine", "abc"):
                cls_name = ""
                local_self = frame[0].f_locals.get("self")
                if local_self is not None:
                    cls_name = type(local_self).__name__
                if cls_name:
                    return f"{cls_name}@{module}:{frame.lineno}"
                return f"{module}:{frame.lineno}"
        return "engine"

    # ----------------------------------------------------------
    # Executor protocol
    # ----------------------------------------------------------

    def execute(self, directive: Sentence) -> Silence:
        """Execute a parsed directive for its side effects."""
        self.dsl.execute_directive(directive)
        return SILENCE

    # ----------------------------------------------------------
    # Document Registry
    # ----------------------------------------------------------

    def register_document(self, name: str, text: str):
        self.documents[name] = text
        self._verifier.index.add(name, text)
        # Corpus claims quantify over the registered documents — a new
        # document changes their closed world, so re-ground them.
        reverify_evidence(self, EVIDENCE_TYPE_CORPUS_QUERY)

    def load_document(self, name: str, path: str):
        with open(path) as f:
            text = f.read()
        self.register_document(name, text)

    # ----------------------------------------------------------
    # Evidence Verification
    # ----------------------------------------------------------

    def _verify_evidence(self, evidence: Evidence, caller: str | None = None) -> Evidence:
        v = self._evidence_verifiers.get(evidence.type)
        if v is None:
            log.warning("No verifier registered for evidence type '%s' — left ungrounded", evidence.type)
            return evidence
        return v.verify(evidence, caller=caller)

    def register_evidence_verifier(self, evidence_type: str, verifier: "EvidenceVerifier") -> None:
        """Register (or replace) the verifier grounding one evidence type."""
        self._evidence_verifiers[evidence_type] = verifier

    def register_entity_alias(self, alias: str, canonical: str) -> None:
        self._entity_aliases[alias] = canonical

    def _canonicalize_entity_aliases(self, expr):
        if not self._entity_aliases:
            return expr
        if isinstance(expr, Symbol):
            return Symbol(self._entity_aliases.get(str(expr), str(expr)))
        if isinstance(expr, (list, tuple)):
            return [self._canonicalize_entity_aliases(item) for item in expr]
        return expr

    def _lookup(self, name: str) -> Axiom | Theorem | Term | None:
        """Find a named item across all stores."""
        if name in self.facts:
            return self.facts[name]
        if name in self.axioms:
            return self.axioms[name]
        if name in self.theorems:
            return self.theorems[name]
        if name in self.terms:
            return self.terms[name]
        return None

    def verify_manual(self, name: str, signature: str = "system"):
        item = self._lookup(name)
        if item is None:
            raise KeyError(f"Unknown: {name}")

        origin = item.origin
        if isinstance(origin, Evidence):
            explanation = (
                f"{origin.explanation} [Signed: {signature}]" if origin.explanation else f"[Signed: {signature}]"
            )
            new_origin = replace(origin, verify_manual=True, signature=signature, explanation=explanation)
        else:
            base = origin if isinstance(origin, str) else str(origin)
            new_origin = Evidence(
                document="manual",
                quotes=[],
                explanation=f"{base} [Signed: {signature}]",
                verify_manual=True,
                signature=signature,
            )

        # Write back under every key that shares this item. Import aliasing
        # registers the same (frozen) object under several names; replacing
        # only the named key would silently split the aliases apart — and
        # all sharing keys must receive the SAME new object, so identity
        # keeps expressing that they are one directive.
        def _sign_store(store: dict[str, _SignableT]) -> None:
            new_item: _SignableT | None = None
            for key, value in store.items():
                if value is item:
                    if new_item is None:
                        new_item = replace(value, origin=new_origin)
                    store[key] = new_item

        _sign_store(self.facts)
        _sign_store(self.axioms)
        _sign_store(self.theorems)
        _sign_store(self.terms)

        log.info("'%s' manually marked as grounded", name)

    # ----------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------

    def evaluate(self, expr: Sentence, local_env=None) -> Sentence:
        """Evaluate an s-expression in the current system."""
        env = {**self.env, **(local_env or {})}
        if self._tracing:
            ts_depth = len(self._tracer_stack)
            try:
                return self._eval(expr, env)
            except Exception:
                # Flush tracer_stack entries from this evaluate() call
                while len(self._tracer_stack) > ts_depth:
                    name, entries = self._tracer_stack.pop()
                    self._trace_log.append((name, entries))
                self._trace_context = self._tracer_stack[-1][0] if self._tracer_stack else None
                self._trace_current = self._tracer_stack[-1][1] if self._tracer_stack else None
                raise
        return self._eval(expr, env)

    def _eval_rewritten(self, expr, env, axiom_scope, restricted):
        """Rewrite an expression then re-evaluate the result."""
        rewritten = self._rewrite(expr, axiom_scope=axiom_scope)
        if rewritten != expr and isinstance(rewritten, (list, tuple)):
            return self._eval(rewritten, env, axiom_scope, restricted)
        return rewritten

    def _axiom_heads(self, axiom_scope=None) -> tuple[set, set]:
        """(head_symbols, var_head_arities) from axiom/theorem LHS patterns.

        Used to skip _rewrite recursion into data whose head has no rules.
        var_head_arities: set of LHS lengths for axioms with ?-var in head
        position (e.g. (map ?f (?x)) has length 3). An expression can only
        match these if its length is in this set.
        Cached per engine; invalidated when axioms/theorems change.
        """
        if axiom_scope is not None:
            heads: set[Symbol] = set()
            var_arities: set[int] = set()
            for rule in axiom_scope:
                wff = rule.wff
                if isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ:
                    lhs = wff[1]
                    if isinstance(lhs, (list, tuple)) and lhs:
                        h = lhs[0]
                        if isinstance(h, Symbol) and str(h).startswith("?"):
                            var_arities.add(len(lhs))
                        else:
                            heads.add(h)
            return heads, var_arities
        cache_key = (len(self.axioms), len(self.theorems))
        if getattr(self, "_axiom_heads_cache_key", None) != cache_key:
            heads = set()
            var_arities = set()
            for rule in list(self.axioms.values()) + list(self.theorems.values()):
                wff = rule.wff
                if isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ:
                    lhs = wff[1]
                    if isinstance(lhs, (list, tuple)) and lhs:
                        h = lhs[0]
                        if isinstance(h, Symbol) and str(h).startswith("?"):
                            var_arities.add(len(lhs))
                        else:
                            heads.add(h)
            self._axiom_heads_cache = (heads, var_arities)
            self._axiom_heads_cache_key = cache_key
        return self._axiom_heads_cache

    def _rewrite_eval_callables(self, expr):
        """Evaluate callable subexpressions in a rewrite result.

        After axiom substitution, expressions like (- 2 1) remain symbolic
        because _rewrite doesn't consult env.  Recurse and evaluate any
        subexpression whose head is a Python callable in self.env with
        fully concrete args.
        """
        if not isinstance(expr, (list, tuple)):
            return expr
        # Recurse first so inner callables reduce before outer ones
        resolved = [self._rewrite_eval_callables(sub) for sub in expr]
        # Now check if this expression itself is a callable with concrete args
        if resolved and isinstance(resolved[0], Symbol) and resolved[0] in self.env and callable(self.env[resolved[0]]):
            args = resolved[1:]
            if all(isinstance(a, (int, float, bool)) for a in args):
                try:
                    return self.env[resolved[0]](*args)
                except Exception:
                    pass
        return resolved

    def _rewrite(self, expr, depth=0, axiom_scope=None, _prev=None):
        """Reduce an expression by applying axioms as rewrite rules.

        Axioms of the form (= LHS RHS) are used left-to-right:
        if expr matches LHS, substitute to get RHS.

        When *axiom_scope* is provided, only those rules are tried;
        otherwise all axioms and theorems in the system are used.
        """
        expr = self._canonicalize_entity_aliases(expr)
        log.info("_rewrite depth=%d expr=%r", depth, expr)
        if depth > 100:
            return expr
        if not isinstance(expr, (list, tuple)):
            return expr

        # (self ...) is an evaluation boundary — contents are evaluated
        # by _eval in the current engine, not rewritten here.
        if expr and expr[0] == SELF:
            return expr

        # Reduce subexpressions first (innermost-first).
        # Skip entirely if head has no axioms — pure data, nothing to rewrite.
        # No axiom LHS starts with a non-Symbol head, so lists/ints/strings
        # as head mean this expression is data — skip immediately.
        heads, var_arities = self._axiom_heads(axiom_scope)
        head = expr[0] if expr else None
        if isinstance(head, Symbol) and str(head) in self._entity_aliases:
            expr = [Symbol(self._entity_aliases[str(head)]), *expr[1:]]
            head = expr[0]
        if not isinstance(head, Symbol):
            return list(expr) if isinstance(expr, tuple) else expr
        if head not in heads:
            if not var_arities or len(expr) not in var_arities:
                return list(expr) if isinstance(expr, tuple) else expr
        expr = [self._rewrite(sub, depth + 1, axiom_scope) for sub in expr]

        # Try axioms and theorems as rewrite rules
        if axiom_scope is not None:
            rules = axiom_scope
        else:
            rules = list(self.axioms.values()) + list(self.theorems.values())
        for rule in rules:
            wff = rule.wff
            if not (isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ):
                continue
            lhs, rhs = self._canonicalize_entity_aliases(wff[1]), wff[2]
            if not isinstance(lhs, (list, tuple)):
                continue
            bindings = match(lhs, expr)
            if bindings is not None:
                result = substitute(rhs, bindings)
                if result == expr or result == _prev:
                    continue  # 1-cycle or 2-cycle — skip
                log.info("_rewrite rule %s: %r -> %r", rule.name, expr, result)
                # ── Trace rewrite ──
                if self._tracing and self._trace_current is not None:
                    self._trace_current.append(("rewrite", rule.name))
                    for var, val in bindings.items():
                        if isinstance(val, Symbol):
                            vname = str(val)
                            if vname in self.facts or vname in self.terms:
                                self._trace_current.append(("resolve", vname))
                result = self._rewrite_eval_callables(result)
                return self._rewrite(result, depth + 1, axiom_scope, _prev=expr)

        return expr

    # Internal: Sentence slots that may be None (tail-call placeholders, strict-pending slots)
    StackSentence = Sentence | None

    def _eval(self, expr: Sentence, env, axiom_scope=None, restricted=False) -> Sentence:
        """Iterative evaluator with delta-compressed stack.

        Key optimisations over v1:
        1. Trail-based env — mutate in place, store only deltas, undo on scope exit.
           Replaces O(n) env.copy() with O(k) trail entries (k = bindings set).
        2. Inline Symbol head resolution — 95 %+ of heads are Symbols that resolve
           from env in O(1).  Only compound heads push _K_HEAD.
        3. Tuple frames — no per-frame dicts, no redundant env/axiom_scope/restricted.
           axiom_scope and restricted are invariant within a single _eval call.
        4. Rewrite cache — keyed by expression identity, populated after first _rewrite.
        """

        # -- Stack & result register --
        stack: list = []
        result: Engine.StackSentence = None
        observer = self._eval_observer
        _rewrite_cache: dict = {}  # id(expr) → rewritten result
        tracing = self._tracing
        tracer_stack = self._tracer_stack  # instance-level, spans recursive _eval calls

        if not hasattr(self, "_eval_trace"):
            self._eval_trace: list[Sentence] = []

        # ── helpers: trail-based env mutation ──
        # trail = [(key, old_value_or_MISSING), ...]
        # _trail_set: save old, write new.  _trail_undo: restore all.

        while True:
            # ── Observer: pre-step ──
            if observer is not None:
                observer(expr, None, stack)

            # ── Depth guard (stack depth, not iteration count) ──
            if len(stack) > self.max_eval_depth:
                trace_str = "\n".join(f"  [{i}] {t!r}" for i, t in enumerate(self._eval_trace[-20:]))
                raise RecursionError(
                    f"maximum eval depth ({self.max_eval_depth}) exceeded "
                    f"while evaluating {expr!r}\n  last 20 eval steps:\n{trace_str}"
                )

            # ── Trace ──
            log.info("_eval expr=%r restricted=%s", expr, restricted)
            self._eval_trace.append(expr)
            if len(self._eval_trace) > 200:
                self._eval_trace = self._eval_trace[-100:]

            # ==============================================================
            # ATOM: Symbol
            # ==============================================================
            if isinstance(expr, Symbol):
                canonical = self._entity_aliases.get(str(expr))
                if canonical is not None:
                    expr = Symbol(canonical)
                    continue
                if expr in env:
                    result = env[expr]
                    log.info("_eval symbol %r -> %r", expr, result)
                    # Trace env-resolved symbols that are known entities
                    if tracing and tracer_stack:
                        name = str(expr)
                        ctx_name, ctx_list = tracer_stack[-1]
                        if ctx_name != name and (name in self.facts or name in self.terms or name in self.theorems):
                            ctx_list.append(("resolve", name))
                else:
                    name = str(expr)
                    if not restricted and name in self.terms:
                        defn = self.terms[name].definition
                        if defn is not None:
                            if tracing:
                                if tracer_stack:
                                    ctx_name, ctx_list = tracer_stack[-1]
                                    if ctx_name != name:
                                        ctx_list.append(("resolve", name))
                                # Push context for any definition (compound or alias)
                                ctx_traces: list[tuple[str, str]] = []
                                stack.append((_K_CONTEXT, name, ctx_traces))
                                tracer_stack.append((name, ctx_traces))
                                self._trace_context = name
                                self._trace_current = ctx_traces
                                log.info("trace context push: term %s", name)
                            expr = defn  # tail-call
                            continue
                        # Forward-declared term (definition is None)
                        if tracing and tracer_stack:
                            ctx_name, ctx_list = tracer_stack[-1]
                            if ctx_name != name:
                                ctx_list.append(("resolve", name))
                        result = expr
                    elif not restricted and name in self.theorems:
                        wff = self.theorems[name].wff
                        if tracing:
                            if tracer_stack:
                                ctx_name, ctx_list = tracer_stack[-1]
                                if ctx_name != name:
                                    ctx_list.append(("resolve", name))
                            if isinstance(wff, (list, tuple)) and wff:
                                ctx_traces = []
                                stack.append((_K_CONTEXT, name, ctx_traces))
                                tracer_stack.append((name, ctx_traces))
                                self._trace_context = name
                                self._trace_current = ctx_traces
                                log.info("trace context push: theorem %s", name)
                                self._trace_current = ctx_traces
                        expr = wff  # tail-call
                        continue
                    elif not restricted and name in self.facts:
                        if tracing and tracer_stack:
                            ctx_name, ctx_list = tracer_stack[-1]
                            if ctx_name != name:
                                ctx_list.append(("resolve", name))
                        result = expr
                    elif self.strict_derive:
                        trace_str = "\n".join(f"  [{i}] {t!r}" for i, t in enumerate(self._eval_trace[-20:]))
                        msg = (
                            f"Unresolved symbol: {expr} — not in :using"
                            if restricted
                            else f"Unresolved symbol: {expr} — not in current system"
                        )
                        cause = ValueError(f"last 20 eval steps:\n{trace_str}")
                        raise NameError(msg) from cause
                    else:
                        # Unresolved symbol — still trace the attempt
                        if tracing and tracer_stack:
                            ctx_name, ctx_list = tracer_stack[-1]
                            if ctx_name != name:
                                ctx_list.append(("resolve", name))
                        result = expr

            # ==============================================================
            # ATOM: non-list, non-Symbol
            # ==============================================================
            elif not isinstance(expr, (list, tuple)):
                result = expr

            # ==============================================================
            # Empty list
            # ==============================================================
            elif not expr:
                result = []

            # ==============================================================
            # COMPOUND expressions
            # ==============================================================
            else:
                head = expr[0]

                # ── :bind — must check before head resolution ──
                if isinstance(head, Symbol) and not str(head).startswith(("?", ":")):
                    bind_raw = expr[-1] if len(expr) >= 3 and expr[-2] == KW_BIND else None
                    if bind_raw is not None:
                        name = str(head)
                        defn = None
                        if name in self.terms and self.terms[name].definition is not None:
                            defn = self.terms[name].definition
                        elif name in self.theorems:
                            defn = self.theorems[name].wff
                        if defn is not None and isinstance(bind_raw, (list, tuple)):
                            pairs = [p for p in bind_raw if isinstance(p, (list, tuple)) and len(p) >= 2]
                            if pairs:
                                # Trail: mutations to env will be undone by _K_TRAIL_UNDO
                                trail: list[tuple] = []
                                stack.append((_K_TRAIL_UNDO, trail))
                                # [tag, pairs, defn, idx, sub_bindings, trail]
                                stack.append([_K_BIND_PAIR, pairs, defn, 0, {}, trail])
                                expr = pairs[0][1]
                                continue
                            else:
                                expr = defn
                                continue

                # ── if ──
                if head == IF:
                    _, cond_expr, then_expr, else_expr = expr
                    # (tag, then, else) — no env/axiom_scope/restricted needed
                    stack.append((_K_IF_COND, then_expr, else_expr))
                    expr = cond_expr
                    continue

                # ── let ──
                if head == LET:
                    _, bindings_expr, body = expr
                    assert isinstance(
                        bindings_expr, (list, tuple)
                    ), f"let bindings must be a list, got {type(bindings_expr)}"
                    let_bindings = [b for b in bindings_expr if isinstance(b, (list, tuple))]
                    if let_bindings:
                        # Trail: undo env mutations when let scope exits
                        trail = []
                        stack.append((_K_TRAIL_UNDO, trail))
                        # [tag, bindings, body, idx, trail]
                        stack.append([_K_LET_BIND, let_bindings, body, 0, trail])
                        expr = let_bindings[0][1]
                        continue
                    else:
                        expr = body
                        continue

                # ── quote ──
                if head == QUOTE:
                    result = expr[1] if len(expr) == 2 else list(expr[1:])

                # ── strict ──
                elif head == STRICT:
                    inner = expr[1]
                    if isinstance(inner, (list, tuple)) and inner and inner[0] == SCOPE and len(inner) > 2:
                        expr = [SCOPE, inner[1]] + [[STRICT, arg] for arg in inner[2:]]
                        continue
                    expr = inner
                    continue

                # ── self ──
                elif head == SELF:
                    args_list = expr[1:]
                    if not args_list:
                        result = []
                    elif len(args_list) == 1:
                        expr = args_list[0]
                        continue
                    else:
                        # [tag, args, idx]
                        stack.append([_K_SELF_ARGS, args_list, 0])
                        expr = args_list[0]
                        continue

                # ── project ──
                elif head == PROJECT:
                    if len(expr) == 2:
                        expr = expr[1]
                        continue
                    basis = expr[1]
                    if basis == SELF:
                        expr = expr[2]
                        continue
                    # (tag, basis_symbol, body)
                    stack.append((_K_PROJECT_BASIS, basis, expr[2]))
                    expr = basis
                    continue

                # ── delegate ──
                elif head == DELEGATE:
                    result = self._eval_delegate(expr, env, axiom_scope, restricted)

                # ── scope ──
                elif head == SCOPE:
                    result = self._eval_scope(expr, env, axiom_scope, restricted)

                # ==========================================================
                # GENERAL: inline head resolution + dispatch
                # ==========================================================
                else:
                    # --- Trace compound head + args ---
                    if tracing and tracer_stack and isinstance(head, Symbol):
                        hname_t = str(head)
                        ctx_name_t, ctx_list_t = tracer_stack[-1]
                        if ctx_name_t != hname_t:
                            if hname_t in self.terms:
                                ctx_list_t.append(("effect", hname_t))
                                ctx_list_t.append(("resolve", hname_t))
                            elif hname_t in self.theorems:
                                ctx_list_t.append(("resolve", hname_t))
                            elif hname_t in self.facts:
                                ctx_list_t.append(("resolve", hname_t))
                        for arg in expr[1:]:
                            if isinstance(arg, Symbol):
                                aname = str(arg)
                                if aname != ctx_name_t and (
                                    aname in self.facts or aname in self.terms or aname in self.theorems
                                ):
                                    ctx_list_t.append(("resolve", aname))

                    # --- Resolve head inline (avoid _K_HEAD for Symbols) ---
                    if isinstance(head, Symbol):
                        if head in env:
                            head_val = env[head]
                        else:
                            hname = str(head)
                            if not restricted and hname in self.terms:
                                defn = self.terms[hname].definition
                                if defn is not None:
                                    if isinstance(defn, (list, tuple)):
                                        # Compound definition — must fully eval.
                                        # Push _K_HEAD, evaluate defn.
                                        stack.append((_K_HEAD, expr))
                                        expr = defn
                                        continue
                                    else:
                                        head_val = defn  # atom (alias)
                                        # Trace: alias term resolves to another named entity
                                        if tracing and isinstance(defn, Symbol):
                                            dname = str(defn)
                                            if dname in self.terms or dname in self.theorems or dname in self.facts:
                                                self._trace_log.append((hname, [("resolve", dname)]))
                                else:
                                    head_val = head  # forward-declared
                            elif not restricted and hname in self.theorems:
                                wff = self.theorems[hname].wff
                                if isinstance(wff, (list, tuple)):
                                    stack.append((_K_HEAD, expr))
                                    expr = wff
                                    continue
                                else:
                                    head_val = wff
                            elif self.strict_derive:
                                raise NameError(
                                    f"Unresolved symbol: {head} — not in :using"
                                    if restricted
                                    else f"Unresolved symbol: {head} — not in current system"
                                )
                            else:
                                head_val = head  # unresolved symbol
                    else:
                        # Compound head (very rare) — must fully eval
                        stack.append((_K_HEAD, expr))
                        expr = head
                        continue

                    # --- head_val resolved: dispatch callable vs lazy ---
                    if callable(head_val):
                        arg_exprs = expr[1:]
                        if not arg_exprs:
                            log.info("_eval head_val=%r callable=True args=[]", head_val)
                            result = head_val()
                            log.info("_eval callable result=%r", result)
                            if result is False and head == EQ:
                                left_rw = self._rewrite([], axiom_scope=axiom_scope)
                                right_rw = self._rewrite([], axiom_scope=axiom_scope)
                                if left_rw == right_rw:
                                    result = True
                        else:
                            # [tag, head_val, head, arg_exprs, evaluated, idx, is_callable, formal_expr]
                            stack.append([_K_ARGS, head_val, head, arg_exprs, [], 0, True, None])
                            expr = arg_exprs[0]
                            continue
                    else:
                        # Lazy path: force-eval (strict ...) args, then rewrite
                        lazy_args: list[Engine.StackSentence] = []
                        strict_pending = []
                        for i, arg in enumerate(expr[1:]):
                            if isinstance(arg, (list, tuple)) and arg and arg[0] == STRICT:
                                strict_pending.append((i, arg[1]))
                                lazy_args.append(None)
                            else:
                                lazy_args.append(arg)

                        if strict_pending:
                            # [tag, head_val, head, expr, lazy_args, strict_pending, strict_idx]
                            stack.append([_K_STRICT_ARG, head_val, head, expr, lazy_args, strict_pending, 0])
                            expr = strict_pending[0][1]
                            continue
                        else:
                            # No strict args — try rewrite immediately
                            rr = self._eval_lazy_rewrite_inline(
                                head_val, head, expr, lazy_args, axiom_scope, stack, _rewrite_cache
                            )
                            if rr is _TAIL_CALL:
                                expr = self._tc_expr  # type: ignore[assignment]
                                continue
                            result = rr

            # ── Observer: post-step (result produced) ──
            if observer is not None:
                observer(expr, result, stack)

            # ==============================================================
            # CONTINUATION DISPATCH — process the stack
            # ==============================================================
            while stack:
                frame = stack[-1]
                tag = frame[0]

                if tag == _K_TRAIL_UNDO:
                    stack.pop()
                    trail = frame[1]
                    # Undo env mutations from :bind / let
                    for key, old in reversed(trail):
                        if old is _MISSING:
                            env.pop(key, None)
                        else:
                            env[key] = old
                    continue  # result passes through

                if tag == _K_CONTEXT:
                    stack.pop()
                    # frame = (_K_CONTEXT, name, ctx_traces)
                    ctx_name = frame[1]
                    ctx_traces = frame[2]
                    if tracing:
                        log.info("trace context pop: %s (%d entries)", ctx_name, len(ctx_traces))
                    self._trace_log.append((ctx_name, ctx_traces))
                    if tracer_stack and tracer_stack[-1][0] == ctx_name:
                        tracer_stack.pop()
                    if tracer_stack:
                        self._trace_context = tracer_stack[-1][0]
                        self._trace_current = tracer_stack[-1][1]
                    else:
                        self._trace_context = None
                        self._trace_current = None
                    continue  # result passes through

                if tag == _K_ARGS:
                    # frame: [tag, head_val, head, arg_exprs, evaluated, idx, is_callable, formal_expr]
                    evaluated = frame[4]
                    evaluated.append(result)
                    idx = frame[5] + 1
                    frame[5] = idx
                    arg_exprs = frame[3]
                    if idx < len(arg_exprs):
                        expr = arg_exprs[idx]
                        break  # back to main loop
                    else:
                        stack.pop()
                        head_val = frame[1]
                        head = frame[2]
                        args = evaluated
                        if frame[6]:  # is_callable
                            log.info("_eval head_val=%r callable=True args=%r", head_val, args)
                            result = head_val(*args)
                            log.info("_eval callable result=%r", result)
                            if result is False and head == EQ and any(isinstance(a, (list, tuple)) for a in args):
                                left_rw = self._rewrite(args[0], axiom_scope=axiom_scope)
                                right_rw = self._rewrite(args[1], axiom_scope=axiom_scope)
                                log.info("_eval EQ rewrite fallback: left_rw=%r right_rw=%r", left_rw, right_rw)
                                if left_rw == right_rw or left_rw == args[1] or right_rw == args[0]:
                                    result = True
                        else:
                            formal_expr = frame[7]
                            ev = [head_val] + args
                            if ev != formal_expr:
                                rewritten2 = self._rewrite(ev, axiom_scope=axiom_scope)
                                if rewritten2 != ev:
                                    new_head2 = (
                                        rewritten2[0]
                                        if isinstance(rewritten2, (list, tuple)) and rewritten2
                                        else rewritten2
                                    )
                                    if new_head2 != head_val:
                                        log.info("_eval post-arg rewrite %r -> %r", ev, rewritten2)
                                        expr = rewritten2
                                        break
                            log.info("_eval formal result=%r", ev)
                            result = ev
                        continue

                elif tag == _K_IF_COND:
                    stack.pop()
                    expr = frame[1] if result else frame[2]
                    break

                elif tag == _K_LET_BIND:
                    # frame: [tag, bindings, body, idx, trail]
                    bindings = frame[1]
                    idx = frame[3]
                    trail = frame[4]
                    key = bindings[idx][0]
                    # Trail-set: save old value, write new
                    old = env.get(key, _MISSING)
                    trail.append((key, old))
                    env[key] = result
                    idx += 1
                    frame[3] = idx
                    if idx < len(bindings):
                        expr = bindings[idx][1]
                        break
                    else:
                        stack.pop()
                        expr = frame[2]  # body
                        break

                elif tag == _K_BIND_PAIR:
                    # frame: [tag, pairs, defn, idx, sub_bindings, trail]
                    pairs = frame[1]
                    idx = frame[3]
                    sub_bindings = frame[4]
                    trail = frame[5]
                    pair = pairs[idx]
                    val = result
                    # Trail-set
                    key = pair[0]
                    old = env.get(key, _MISSING)
                    trail.append((key, old))
                    env[key] = val
                    if not isinstance(val, (list, tuple)):
                        sub_bindings[key] = val
                    idx += 1
                    frame[3] = idx
                    if idx < len(pairs):
                        expr = pairs[idx][1]
                        break
                    else:
                        stack.pop()
                        defn = frame[2]
                        assert defn is not None  # defn set at _K_LET_BIND push
                        bound = substitute(defn, sub_bindings) if sub_bindings else defn
                        expr = bound
                        break

                elif tag == _K_SELF_ARGS:
                    # frame: [tag, args, idx]
                    idx = frame[2] + 1
                    frame[2] = idx
                    args_list = frame[1]
                    if idx < len(args_list):
                        if idx == len(args_list) - 1:
                            stack.pop()
                        expr = args_list[idx]
                        break
                    else:
                        stack.pop()
                        continue

                elif tag == _K_HEAD:
                    # frame: (_K_HEAD, original_expr)
                    stack.pop()
                    head_val = result
                    original_expr = frame[1]
                    head = original_expr[0]

                    if callable(head_val):
                        arg_exprs = original_expr[1:]
                        if not arg_exprs:
                            log.info("_eval head_val=%r callable=True args=[]", head_val)
                            result = head_val()
                            log.info("_eval callable result=%r", result)
                            if result is False and head == EQ:
                                left_rw = self._rewrite([], axiom_scope=axiom_scope)
                                right_rw = self._rewrite([], axiom_scope=axiom_scope)
                                if left_rw == right_rw:
                                    result = True
                            continue
                        stack.append([_K_ARGS, head_val, head, arg_exprs, [], 0, True, None])
                        expr = arg_exprs[0]
                        break
                    else:
                        # Lazy path
                        lazy_args = []  # list[Engine.StackSentence]
                        strict_pending = []
                        for i, arg in enumerate(original_expr[1:]):
                            if isinstance(arg, (list, tuple)) and arg and arg[0] == STRICT:
                                strict_pending.append((i, arg[1]))
                                lazy_args.append(None)
                            else:
                                lazy_args.append(arg)
                        if strict_pending:
                            stack.append([_K_STRICT_ARG, head_val, head, original_expr, lazy_args, strict_pending, 0])
                            expr = strict_pending[0][1]
                            break
                        else:
                            rr = self._eval_lazy_rewrite_inline(
                                head_val, head, original_expr, lazy_args, axiom_scope, stack, _rewrite_cache
                            )
                            if rr is _TAIL_CALL:
                                expr = self._tc_expr  # type: ignore[assignment]
                                break
                            result = rr
                            continue

                elif tag == _K_STRICT_ARG:
                    # frame: [tag, head_val, head, expr, lazy_args, strict_pending, strict_idx]
                    pos, _ = frame[5][frame[6]]
                    frame[4][pos] = result
                    frame[6] += 1
                    if frame[6] < len(frame[5]):
                        expr = frame[5][frame[6]][1]
                        break
                    else:
                        stack.pop()
                        rr = self._eval_lazy_rewrite_inline(
                            frame[1], frame[2], frame[3], frame[4], axiom_scope, stack, _rewrite_cache
                        )
                        if rr is _TAIL_CALL:
                            expr = self._tc_expr  # type: ignore[assignment]
                            break
                        result = rr
                        continue

                elif tag == _K_PROJECT_BASIS:
                    # frame: (_K_PROJECT_BASIS, basis_symbol, body)
                    stack.pop()
                    basis_val = result
                    if callable(basis_val):
                        body = frame[2]
                        result = basis_val(frame[1], *([body] if not isinstance(body, (list, tuple)) else [body]))
                        continue
                    raise TypeError(f"project basis is not callable: {basis_val!r}")

            else:
                # Stack empty — we're done
                if tracing and tracer_stack:
                    log.info("trace: _eval returning with %d stale tracer_stack entries", len(tracer_stack))
                assert result is not None  # _eval always produces a value
                return result

    # Single-slot for tail-call signaling (avoids tuple allocation)
    _tc_expr: StackSentence = None

    def _eval_lazy_rewrite_inline(self, head_val, head, original_expr, lazy_args, axiom_scope, stack, cache):
        """Lazy rewrite path for non-callable heads.

        Returns result value, or _TAIL_CALL sentinel (sets self._tc_expr).
        Uses cache to skip redundant _rewrite calls.
        """
        formal_expr = [head_val] + lazy_args

        # --- Rewrite (with cache) ---
        eid = id(original_expr)
        cached = cache.get(eid)
        if cached is not None:
            rewritten = cached
        else:
            rewritten = self._rewrite(formal_expr, axiom_scope=axiom_scope)
            cache[eid] = rewritten

        if rewritten != formal_expr:
            new_head = rewritten[0] if isinstance(rewritten, (list, tuple)) and rewritten else rewritten
            if new_head != head_val:
                log.info("_eval lazy rewrite %r -> %r", formal_expr, rewritten)
                self._tc_expr = rewritten
                return _TAIL_CALL

        # No rewrite or same head — evaluate args
        if isinstance(head_val, (list, tuple)):
            return formal_expr  # data guard

        arg_exprs = original_expr[1:]
        if not arg_exprs:
            log.info("_eval formal result=%r", formal_expr)
            return formal_expr

        # Push arg evaluation
        # [tag, head_val, head, arg_exprs, evaluated, idx, is_callable, formal_expr]
        stack.append([_K_ARGS, head_val, head, arg_exprs, [], 0, False, formal_expr])
        self._tc_expr = arg_exprs[0]
        return _TAIL_CALL

    def _eval_delegate(self, expr, env, axiom_scope, restricted):
        """Evaluate (delegate ...) — kept as recursive helper (rare, shallow)."""
        depth = 0
        delegate_pattern: Engine.StackSentence = None
        e: Sentence = expr
        while isinstance(e, (list, tuple)) and e and e[0] == DELEGATE:
            depth += 1
            if len(e) > 2 and e[2] != KW_BIND:
                delegate_pattern = e[1]
                e = e[2]
            else:
                e = e[1]
        delegate_body: Sentence = e
        binds = get_keyword(expr, KW_BIND, [])

        def _resolve_proj_delegate(ex: Sentence) -> Sentence:
            if not isinstance(ex, (list, tuple)) or not ex:
                return ex
            if ex[0] == PROJECT:
                return self._eval(ex, env, axiom_scope, restricted)
            return [_resolve_proj_delegate(x) for x in ex]

        self_proposal: Sentence = []
        try:
            resolved_body: Sentence = _resolve_proj_delegate(delegate_body)
            self_proposal = self._eval(resolved_body, env, axiom_scope, restricted)
        except (NameError, TypeError):
            pass
        log.info("_delegate self_proposal=%r", self_proposal)
        env[Symbol("?_self")] = self_proposal

        if delegate_pattern is not None and self_proposal != [] and Symbol("?_self") in free_vars(delegate_pattern):
            try:
                pattern_result = self._eval(delegate_pattern, env, axiom_scope, restricted)
                if pattern_result:
                    return self_proposal
            except (NameError, TypeError):
                pass

        found = 0
        for proposal in reversed(binds):
            if proposal != []:
                found += 1
                if found == depth:
                    return proposal
        raise NameError(f"delegate depth {depth} but only {found} matching proposals: {to_sexp(expr)}")

    def _eval_scope(self, expr, env, axiom_scope, restricted):
        """Evaluate (scope ...) — kept as recursive helper (scope boundary)."""
        scope_name: Sentence = expr[1]
        if scope_name == SELF:

            def _self_scope(_name, *args):
                result = None
                for arg in args:
                    if isinstance(arg, (list, tuple)):
                        result = self._eval(arg, env, axiom_scope, restricted)
                    else:
                        result = arg
                return result

            scope_val: Sentence | Callable = _self_scope
        else:
            scope_val = self._eval(scope_name, env, axiom_scope, restricted)
        if callable(scope_val):

            def _resolve_projects(ex):
                if not isinstance(ex, (list, tuple)) or not ex:
                    return ex
                if ex[0] == PROJECT:
                    resolved = self._eval(ex, env, axiom_scope, restricted)
                    log.info("_resolve_projects %r -> %r", ex, resolved)
                    return resolved
                return [_resolve_projects(x) for x in ex]

            def _delegate_proposal(delegate_expr):
                pattern = None
                e = delegate_expr
                while isinstance(e, (list, tuple)) and e and e[0] == DELEGATE:
                    if len(e) > 2 and e[2] != KW_BIND:
                        pattern = e[1]
                        e = e[2]
                    else:
                        e = e[1]
                body = e
                log.info("_delegate_proposal body=%r pattern=%r", body, pattern)

                existing = get_keyword(delegate_expr, KW_BIND, [])
                level = len(existing) + 1
                log.info("_delegate_proposal level=%d existing=%d", level, len(existing))

                all_vars = set()
                if pattern:
                    all_vars |= free_vars(pattern)
                all_vars |= free_vars(body)

                bindings: dict[Symbol, Sentence] = {}
                self_var = Symbol("?_self")
                needs_self = self_var in all_vars

                for var in all_vars:
                    vname = str(var)
                    if vname == "?_level":
                        bindings[var] = level
                        continue
                    if vname == "?_self":
                        continue
                    if vname.startswith("?..."):
                        plain = Symbol(vname[4:])
                    else:
                        plain = Symbol(vname[1:])
                    try:
                        bindings[var] = self._eval(plain, env, axiom_scope, restricted)
                    except (NameError, TypeError):
                        return []

                bound_body = substitute(body, bindings)
                bound_body = _resolve_projects(bound_body)

                result = self._eval(bound_body, env, axiom_scope, restricted)
                if needs_self:
                    bindings[self_var] = result

                if pattern is not None:
                    bound_pattern = substitute(pattern, bindings)
                    bound_pattern = _resolve_projects(bound_pattern)
                    try:
                        pattern_ok = self._eval(bound_pattern, env, axiom_scope, restricted)
                    except (NameError, TypeError):
                        return []
                    if not pattern_ok:
                        return []
                log.info("_delegate_proposal result=%r", result)
                return result

            def _rp(e):
                if not isinstance(e, (list, tuple)) or not e:
                    return e
                if e[0] == PROJECT:
                    return self._eval(e, env, axiom_scope, restricted)
                if e[0] == DELEGATE:
                    existing = get_keyword(e, KW_BIND, [])
                    try:
                        proposal = _delegate_proposal(e)
                        new_binds = existing + [proposal]
                    except (NameError, TypeError):
                        new_binds = existing + [[]]
                    base = []
                    for x in e:
                        if x == KW_BIND:
                            break
                        base.append(x)
                    return base + [KW_BIND, new_binds]
                log.info("_rp recurse head=%r len=%d", e[0], len(e))
                return [_rp(x) for x in e]

            resolved = [_rp(a) for a in expr[2:]]
            log.info("_rp scope=%r resolved=%r", scope_name, resolved)
            return scope_val(scope_name, *resolved)
        raise TypeError(f"scope target is not callable: {scope_val!r}")

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------

    def _check_wff(self, expr):
        """Check that an expression is well-formed in the current system."""
        if isinstance(expr, Symbol):
            if expr in self.env or str(expr) in self.terms:
                return
            if expr in SPECIAL_FORMS:
                return
            # if expr == SILENCE:
            #     return
            if len(expr) == 1 and expr.isalpha():
                return
            if expr.startswith("?"):
                return
            raise NameError(f"Symbol '{expr}' not in current system. Introduce it first.")
        if isinstance(expr, (list, tuple)):
            for sub in expr:
                self._check_wff(sub)

    def _check_consistency(self, new_wff):
        """Check that adding this WFF doesn't create contradiction."""
        try:
            result = self.evaluate(new_wff)
            for name, ax in self.axioms.items():
                try:
                    existing = self.evaluate(ax.wff)
                    if isinstance(result, bool) and isinstance(existing, bool):
                        if to_sexp(new_wff) == to_sexp(ax.wff) and result != existing:
                            raise ValueError(f"Contradiction: new axiom contradicts '{name}'")
                except (NameError, TypeError):
                    continue
        except (NameError, TypeError):
            pass

    def _register_if_definition(self, name: str, wff):
        """If the axiom defines a value, register it."""
        if isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ and isinstance(wff[1], Symbol):
            try:
                val = self.evaluate(wff[2])
                self.env[wff[1]] = val
            except (NameError, TypeError):
                pass

    # ----------------------------------------------------------
    # Derivation
    # ----------------------------------------------------------

    def _check_sources_grounded(self, using: list[str]) -> list[str]:
        """Check if any source in `:using` has unverified evidence.

        Returns list of ungrounded source names.
        """
        ungrounded = []
        for src_name in using:
            origin = None
            if src_name in self.facts:
                origin = self.facts[src_name].origin
            if src_name in self.axioms:
                origin = self.axioms[src_name].origin
            if src_name in self.theorems:
                origin = self.theorems[src_name].origin
            if src_name in self.terms:
                origin = self.terms[src_name].origin

            if isinstance(origin, Evidence) and not origin.is_grounded:
                ungrounded.append(src_name)
            # If origin is "potential fabrication" string from a prior derive
            if isinstance(origin, str) and "potential fabrication" in origin:
                ungrounded.append(src_name)

        return ungrounded

    @staticmethod
    def _expr_symbols(expr) -> set[str]:
        """Extract all non-?-prefixed symbol names from an expression."""
        if isinstance(expr, Symbol) and not str(expr).startswith("?"):
            return {str(expr)}
        if isinstance(expr, (list, tuple)):
            result: set[str] = set()
            for sub in expr:
                result |= Engine._expr_symbols(sub)
            return result
        return set()

    def _expand_using(self, using: list[str]) -> list[str]:
        """Transitively expand :using by pulling in symbols referenced by axioms/terms."""
        resolved: set[str] = set()
        pending = set(using)
        while pending:
            name = pending.pop()
            if name in resolved:
                continue
            resolved.add(name)
            # Collect symbols from axiom/theorem WFFs
            if name in self.axioms:
                deps = self._expr_symbols(self.axioms[name].wff)
                pending |= deps - resolved
            if name in self.theorems:
                deps = self._expr_symbols(self.theorems[name].wff)
                pending |= deps - resolved
            # Collect symbols from term definitions
            if name in self.terms and self.terms[name].definition is not None:
                deps = self._expr_symbols(self.terms[name].definition)
                pending |= deps - resolved
        return list(resolved)

    def _build_restricted_env(self, using: list[str]) -> dict:
        """Build an evaluation environment restricted to :using sources.

        Transitively expands :using — symbols referenced in axiom WFFs
        and term definitions are automatically included.
        """
        expanded = self._expand_using(using)
        log.info("_build_restricted_env: %r expanded to %r", using, expanded)
        env: dict = {}
        # Include callable operators (arithmetic, comparison, logic)
        for sym, val in self.env.items():
            if callable(val):
                env[sym] = val
        for src_name in expanded:
            if src_name in self.facts:
                env[Symbol(src_name)] = self.facts[src_name].wff
            elif src_name in self.terms:
                term = self.terms[src_name]
                if term.definition is not None:
                    try:
                        env[Symbol(src_name)] = self.evaluate(term.definition)
                    except (NameError, TypeError):
                        env[Symbol(src_name)] = Symbol(src_name)
                else:
                    # Forward-declared: resolve to own symbol for rewriting
                    env[Symbol(src_name)] = Symbol(src_name)
            elif src_name in self.theorems:
                env[Symbol(src_name)] = self.evaluate(self.theorems[src_name].wff)
        return env

    def _collect_using_rules(self, using: list[str]) -> list[Axiom | Theorem]:
        """Collect axiom/theorem objects from :using (expanded transitively)."""
        expanded = self._expand_using(using)
        rules: list[Axiom | Theorem] = []
        for src_name in expanded:
            if src_name in self.axioms:
                rules.append(self.axioms[src_name])
            if src_name in self.theorems:
                rules.append(self.theorems[src_name])
        return rules

    def derive(self, name: str, wff, using: list[str]) -> Theorem:
        """Derive a theorem from existing axioms/terms.

        Evaluation is restricted to facts/terms listed in :using.
        Axiom rewrite rules are scoped to axioms/theorems in :using.
        If any source has unverified evidence, the theorem is
        marked as 'potential fabrication' with a trace to the unverified sources.
        """
        if isinstance(wff, str):
            wff = PGStringParser.translate(wff)

        for ax_name in using:
            if (
                ax_name not in self.axioms
                and ax_name not in self.facts
                and ax_name not in self.terms
                and ax_name not in self.theorems
            ):
                raise ValueError(f"Unknown axiom, fact, term, or theorem: {ax_name}")

        # Evaluate: restricted (strict) or global (legacy) mode
        if self.strict_derive:
            restricted_env = self._build_restricted_env(using)
            axiom_scope = self._collect_using_rules(using)
            try:
                result = self._eval(wff, restricted_env, axiom_scope=axiom_scope, restricted=True)
            except NameError as e:
                raise NameError(f"Derivation '{name}' references symbols not in :using: {e}") from e
        else:
            result = self.evaluate(wff)
        does_not_hold = result is False or result is None

        if does_not_hold:
            log.warning("Derivation '%s' does not hold: %s evaluated to False", name, to_sexp(wff))

        # Check fabrication propagation
        ungrounded = self._check_sources_grounded(using)
        issues = []
        if does_not_hold:
            issues.append("does not hold (evaluated to False)")
        if ungrounded:
            issues.append(f"derived from unverified: {', '.join(ungrounded)}")
            log.warning(
                "Derivation '%s' marked as potential fabrication (unverified sources: %s)",
                name,
                ", ".join(ungrounded),
            )

        if issues:
            origin = f"potential fabrication — {'; '.join(issues)}"
        else:
            origin = "derived"

        thm = Theorem(name=name, wff=wff, derivation=using, origin=origin)
        self.theorems[name] = thm
        return thm

    # ----------------------------------------------------------
    # Diff
    # ----------------------------------------------------------

    @staticmethod
    def _expr_references(expr, name: str) -> bool:
        """Check if an expression tree contains a Symbol matching name."""
        if isinstance(expr, Symbol):
            return str(expr) == name
        if isinstance(expr, (list, tuple)):
            return any(Engine._expr_references(sub, name) for sub in expr)
        return False

    def _dependents(self, symbol_name: str, exclude_diff: str | None = None) -> list[tuple[str, str]]:
        """Find all definitions that transitively reference a symbol.

        Returns a list of (name, kind) tuples where kind is one of
        'term', 'fact', 'axiom', 'theorem', or 'diff'.

        Args:
            exclude_diff: diff name to exclude (the calling diff itself).
        """
        references = self._expr_references

        def _all_named_exprs():
            for n, t in self.terms.items():
                yield n, "term", t.definition
            for n, f in self.facts.items():
                yield n, "fact", f.wff
            for n, a in self.axioms.items():
                yield n, "axiom", a.wff
            for n, th in self.theorems.items():
                yield n, "theorem", th.wff
            for n, d in self.diffs.items():
                if n != exclude_diff:
                    yield n, "diff", [Symbol(d["replace"]), Symbol(d["with"])]

        def _mentions(name_to_find, n, kind, expr):
            """Check if a definition mentions name_to_find — via expression
            symbols OR via the theorem's derivation (`:using`) list.

            Theorems whose WFF was evaluated to a literal at derive-time
            no longer contain Symbol references, but their .derivation
            records the names they depended on.
            """
            if references(expr, name_to_find):
                return True
            if kind == "theorem" and name_to_find in self.theorems[n].derivation:
                return True
            return False

        direct: set[tuple[str, str]] = set()
        for n, kind, expr in _all_named_exprs():
            if _mentions(symbol_name, n, kind, expr):
                direct.add((n, kind))

        result: set[tuple[str, str]] = set()
        frontier = direct
        while frontier:
            result |= frontier
            frontier_names = {n for n, _ in frontier}
            next_frontier: set[tuple[str, str]] = set()
            for n, kind, expr in _all_named_exprs():
                if (n, kind) not in result and any(_mentions(fn, n, kind, expr) for fn in frontier_names):
                    next_frontier.add((n, kind))
            frontier = next_frontier
        return list(result)

    def register_diff(self, name: str, replace: str, with_: str):
        """Register a diff — a lazy comparison between two symbols.

        Stores only the parameters. The result is computed fresh on
        every call to eval_diff() or consistency().
        """
        self.diffs[name] = {"replace": replace, "with": with_}
        self.diff_refs.setdefault(replace, set()).add(name)
        self.diff_refs.setdefault(with_, set()).add(name)
        log.debug("Diff registered '%s': %s vs %s", name, replace, with_)

    def _resolve_value(self, name: str):
        """Resolve a symbol to its value (evaluated) or definition (formal)."""
        if Symbol(name) in self.env:
            return self.env[Symbol(name)]
        if name in self.terms:
            defn = self.terms[name].definition
            if defn is None:
                return Symbol(name)
            try:
                return self.evaluate(defn)
            except (NameError, TypeError):
                return defn
        if name in self.facts:
            return self.facts[name].wff
        if name in self.theorems:
            try:
                return self.evaluate(self.theorems[name].wff)
            except (NameError, TypeError):
                return self.theorems[name].wff
        if name in self.axioms:
            return self.axioms[name].wff
        raise KeyError(f"Unknown symbol: {name}")

    def eval_diff(self, name: str) -> DiffResult:
        """Evaluate a registered diff against current system state.

        Transitively scans dependencies via _dependents, following not
        just direct references but also theorem derivation chains.
        Excludes itself from its own dependency scan to avoid circular
        self-contamination.  Dependent diffs that reference the replaced
        symbol are flagged as contaminated.  Theorems whose derivation
        chain used the replaced symbol — even when their WFF is a literal
        — are flagged as contaminated.
        """
        if name not in self.diffs:
            raise KeyError(f"Unknown diff: {name}")

        params = self.diffs[name]
        replace = params["replace"]
        with_ = params["with"]

        original = self._resolve_value(replace)
        substitute_val = self._resolve_value(with_)

        affected = self._dependents(replace, exclude_diff=name)

        divergences: dict[str, list] = {}
        for dep_name, dep_kind in affected:
            if dep_kind == "term":
                term_def = self.terms[dep_name].definition
                if term_def is None:
                    continue  # forward-declared primitive — no definition to diverge
                defn = term_def
            elif dep_kind == "fact":
                defn = self.facts[dep_name].wff
            elif dep_kind == "axiom":
                defn = self.axioms[dep_name].wff
            elif dep_kind == "theorem":
                defn = self.theorems[dep_name].wff
            elif dep_kind == "diff":
                # The dependent diff references the replaced symbol
                # in its :replace or :with — flag as contaminated.
                dep_params = self.diffs[dep_name]
                divergences[dep_name] = [
                    f"diff({dep_params['replace']} vs {dep_params['with']})",
                    f"<contaminated: references {replace}>",
                ]
                continue
            else:
                continue

            # For theorems found via .derivation whose WFF is already
            # evaluated to a literal: substitution into the WFF won't
            # change anything, but the derivation *used* the replaced
            # symbol so the result is contaminated.  Flag as divergent
            # since re-derivation with different input could change
            # the outcome.
            if (
                dep_kind == "theorem"
                and not self._expr_references(defn, replace)
                and replace in self.theorems[dep_name].derivation
            ):
                divergences[dep_name] = [defn, f"<contaminated: uses {replace}>"]
                continue

            try:
                result_a = self.evaluate(defn)
                result_b = self.evaluate(defn, {Symbol(replace): substitute_val})
            except (NameError, TypeError):
                # Formal expressions — compare structurally via substitution
                result_a = defn
                result_b = substitute(defn, {Symbol(replace): substitute_val})
            if result_a != result_b:
                divergences[dep_name] = [result_a, result_b]

        return DiffResult(
            name=name,
            replace=replace,
            with_=with_,
            value_a=original,
            value_b=substitute_val,
            divergences=divergences,
        )

    # ----------------------------------------------------------
    # Retract / Rederive
    # ----------------------------------------------------------

    def retract(self, name: str):
        """Remove a fact, axiom, term, theorem, or diff from the system."""
        removed = False
        if name in self.facts:
            del self.facts[name]
            removed = True
        if name in self.axioms:
            del self.axioms[name]
            removed = True
        if name in self.theorems:
            del self.theorems[name]
            removed = True
        if name in self.terms:
            del self.terms[name]
            removed = True
        if name in self.diffs:
            params = self.diffs[name]
            for ref in (params["replace"], params["with"]):
                if ref in self.diff_refs:
                    self.diff_refs[ref].discard(name)
                    if not self.diff_refs[ref]:
                        del self.diff_refs[ref]
            del self.diffs[name]
            removed = True
        if Symbol(name) in self.env:
            del self.env[Symbol(name)]
        if not removed:
            raise KeyError(f"Unknown: {name}")
        log.debug("'%s' retracted from system", name)

    def rederive(self, name: str):
        """Re-run a derivation to refresh its fabrication status.

        Useful after overriding evidence on a source that was previously
        flagged, which made derived theorems stale.
        """
        if name not in self.theorems:
            raise KeyError(f"Unknown theorem: {name}")
        thm = self.theorems[name]

        # Re-derive: re-check sources and replace with updated origin
        ungrounded = self._check_sources_grounded(thm.derivation)
        if ungrounded:
            new_origin = f"potential fabrication — derived from unverified: {', '.join(ungrounded)}"
            log.warning("Rederive '%s': still has unverified sources: %s", name, ", ".join(ungrounded))
        else:
            new_origin = "derived"
            log.info("Rederive '%s': sources now verified — cleared", name)
        self.theorems[name] = replace(thm, origin=new_origin)

    # ----------------------------------------------------------
    # Consistency
    # ----------------------------------------------------------

    def _check_evidence(self) -> tuple[list[ConsistencyIssue], list[ConsistencyWarning]]:
        """Check evidence grounding and fabrication propagation."""
        issues: list[ConsistencyIssue] = []
        warnings: list[ConsistencyWarning] = []

        # 1. Evidence grounding
        unverified = []
        manually_verified = []
        no_evidence = []
        absence_violated = []
        obligation_violated = []

        for store in [self.facts, self.axioms, self.theorems, self.terms]:
            for name, item in store.items():  # type: ignore[attr-defined]
                origin = item.origin
                if isinstance(origin, Evidence):
                    if not origin.verified and origin.verify_manual:
                        manually_verified.append(name)
                    elif not origin.is_grounded:
                        violated = _corpus_counter_examples(origin)
                        if violated is not None:
                            if _corpus_polarity(origin) == "forall":
                                obligation_violated.append((name, violated))
                            else:
                                absence_violated.append((name, violated))
                        else:
                            unverified.append((name, origin.quotes + _corpus_reasons(origin)))
                elif isinstance(origin, str):
                    if (
                        origin not in ("unknown", "derived")
                        and not origin.startswith("diff ")
                        and "potential fabrication" not in origin
                    ):
                        no_evidence.append((name, origin))

        if unverified:
            issues.append(ConsistencyIssue(IssueType.UNVERIFIED_EVIDENCE, sorted(unverified, key=lambda x: x[0])))
        if no_evidence:
            issues.append(ConsistencyIssue(IssueType.NO_EVIDENCE, sorted(no_evidence, key=lambda x: x[0])))
        if absence_violated:
            issues.append(ConsistencyIssue(IssueType.ABSENCE_VIOLATED, sorted(absence_violated, key=lambda x: x[0])))
        if obligation_violated:
            issues.append(
                ConsistencyIssue(IssueType.OBLIGATION_VIOLATED, sorted(obligation_violated, key=lambda x: x[0]))
            )
        if manually_verified:
            manual_details = {}
            for name in manually_verified:
                stores: list[dict] = [self.facts, self.axioms, self.theorems, self.terms]
                for store in stores:
                    if name in store:
                        origin = store[name].origin
                        if isinstance(origin, Evidence):
                            parts = []
                            if origin.explanation:
                                parts.append(origin.explanation)
                            if origin.quotes:
                                parts.append(f"quotes: {origin.quotes}")
                            if origin.document and origin.document != "manual":
                                parts.append(f"(source: {origin.document})")
                            manual_details[name] = " ".join(parts) if parts else "manually verified"
                        elif origin:
                            manual_details[name] = str(origin)
                        else:
                            manual_details[name] = "no origin provided"
                        break
                else:
                    manual_details[name] = "no origin provided"
            warnings.append(
                ConsistencyWarning(WarningType.MANUALLY_VERIFIED, sorted(manually_verified), manual_details)
            )

        # 2. Fabrication propagation
        fabrications = sorted(
            name
            for name, thm in self.theorems.items()
            if isinstance(thm.origin, str) and "potential fabrication" in thm.origin
        )
        if fabrications:
            issues.append(ConsistencyIssue(IssueType.POTENTIAL_FABRICATION, fabrications))

        return issues, warnings

    def _check_diffs(
        self, diff_names: set[str] | None = None
    ) -> tuple[list[ConsistencyIssue], list[ConsistencyWarning]]:
        """Evaluate diffs and return issues/warnings.

        If diff_names is given, only those diffs are evaluated.
        If None, all diffs are evaluated.
        """
        issues: list[ConsistencyIssue] = []
        warnings: list[ConsistencyWarning] = []

        names = diff_names if diff_names is not None else set(self.diffs)
        all_diffs = sorted((self.eval_diff(n) for n in names), key=lambda d: d.name)
        downstream_divergent = [d for d in all_diffs if not d.empty and not d.diff_contamination_only]
        diff_contamination = [d for d in all_diffs if d.diff_contamination_only]
        value_divergent = [d for d in all_diffs if d.values_diverge and d.empty]
        if downstream_divergent:
            issues.append(ConsistencyIssue(IssueType.DIFF_DIVERGENCE, downstream_divergent))
        if value_divergent:
            issues.append(ConsistencyIssue(IssueType.DIFF_VALUE_DIVERGENCE, value_divergent))
        if diff_contamination:
            contam_details = {}
            for d in diff_contamination:
                contam_details[d.name] = "; ".join(f"{k}: {v[1]}" for k, v in sorted(d.divergences.items()))
            warnings.append(
                ConsistencyWarning(WarningType.DIFF_CONTAMINATION, [d.name for d in diff_contamination], contam_details)
            )

        confounded_details = {}
        for name in sorted(names):
            params = self.diffs[name]
            replace_quotes = _evidence_quote_provenance(self, params["replace"])
            with_quotes = _evidence_quote_provenance(self, params["with"])
            overlap = _confounded_quote_pairs(replace_quotes, with_quotes)
            if overlap:
                entries = []
                for document, replace_quote, with_quote in overlap:
                    replace_via = ", ".join(sorted(replace_quotes[(document, replace_quote)]))
                    with_via = ", ".join(sorted(with_quotes[(document, with_quote)]))
                    quote_display = (
                        repr(replace_quote)
                        if replace_quote == with_quote
                        else f"{replace_quote!r} overlaps {with_quote!r}"
                    )
                    entries.append(f"{document}: {quote_display} (replace via {replace_via}; with via {with_via})")
                confounded_details[name] = "; ".join(entries)
        if confounded_details:
            warnings.append(
                ConsistencyWarning(
                    WarningType.CONFOUNDED_EVIDENCE,
                    sorted(confounded_details),
                    confounded_details,
                )
            )

        return issues, warnings

    def consistency(self, suppress_log: bool = True) -> ConsistencyReport:
        """Check full consistency state of the system.

        Checks three layers:
          1. Evidence grounding — are all quotes verified?
          2. Fabrication propagation — any derived axioms tainted?
          3. Diff agreement — do cross-checked values agree?
        """
        issues, warnings = self._check_evidence()
        diff_issues, diff_warnings = self._check_diffs()
        issues.extend(diff_issues)
        warnings.extend(diff_warnings)

        report = ConsistencyReport(
            consistent=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )

        if not suppress_log:
            log.info("%s", report) if report.consistent else log.warning("%s", report)
        return report

    # ----------------------------------------------------------
    # Axiom / Term / Fact introduction (engine-level)
    # ----------------------------------------------------------

    def introduce_axiom(self, name: str, wff, origin) -> Axiom:
        """Introduce a new axiom. Validates WFF and checks consistency."""
        if isinstance(wff, str):
            wff = PGStringParser.translate(wff)

        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        if not free_vars(wff):
            raise ValueError(
                f"Axiom '{name}' has no ?-variables — it is a ground statement. "
                f"Use (fact ...) for ground values or (derive ...) for provable claims."
            )

        self._check_wff(wff)

        ax = Axiom(name=name, wff=wff, origin=origin)
        self.axioms[name] = ax
        self._register_if_definition(name, wff)
        return ax

    def introduce_term(self, name: str, definition, origin) -> Term:
        """Introduce a new term/concept."""
        if isinstance(definition, str):
            definition = PGStringParser.translate(definition)

        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        term = Term(name=name, definition=definition, origin=origin)
        self.terms[name] = term
        return term

    def set_fact(self, name: str, value: WFF, origin):
        """Set a ground truth value with evidence."""
        if isinstance(origin, Evidence):
            origin = self._verify_evidence(origin, caller=name)

        if name in self.facts:
            if not self.overridable:
                raise ValueError(
                    f"Fact '{name}' already exists. Use retract() first, or create System(overridable=True)"
                )
            log.info("Overwriting fact '%s': %s → %s", name, self.facts[name].wff, value)

        self.facts[name] = Fact(name=name, wff=value, origin=origin)
        self.env[Symbol(name)] = value

    def instantiate(self, name: str, bindings: dict):
        """Look up a parameterized axiom or term, substitute ?-vars, return concrete expression."""
        if name in self.axioms:
            template = self.axioms[name].wff
        elif name in self.theorems:
            template = self.theorems[name].wff
        elif name in self.terms:
            defn = self.terms[name].definition
            if defn is None:
                raise KeyError(f"Cannot instantiate forward-declared term: {name}")
            template = defn
        else:
            raise KeyError(f"Unknown axiom, theorem, or term: {name}")

        return substitute(template, bindings)


# ============================================================
# DSL Loader
# ============================================================


def load_source(engine: Engine, source: str) -> Silence:
    """Back-compat shim — the logic lives on engine.dsl (DslLoader)."""
    return engine.dsl.load_source(source)
