"""QueryEngine — the corpus-generic query language over a DocumentSearchIndex.

Search is core machinery: any DocumentIndex — registered documents, file
corpora — wraps in a DocumentSearchIndex and answers the same s-expression
query language. The bench's SearchSystem2 composes this engine with its
scopes, morphisms, and display operators; the document-corpus evidence
verifier evaluates claims through it directly.

The operator implementations moved here verbatim from SearchSystem2; the
bench-only operators (scope registration/delegation, sr-form conversion)
stayed there. ``form_to_posting`` is the extension hook through which the
bench injects its posting-morphism for cross-scope form arguments; the
default treats foreign forms as empty postings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import Sentence, is_sentence_list

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier import DocumentIndex

    from .index import DocumentSearchIndex

Posting = dict


class QueryEngine:
    """Posting-set query operators + evaluation over one search index."""

    def __init__(
        self,
        index: "DocumentIndex | DocumentSearchIndex",
        form_to_posting: "Callable | None" = None,
    ):
        from parseltongue.core.system import System as PltgSystem

        from .index import DocumentSearchIndex

        if isinstance(index, DocumentSearchIndex):
            self._index = index._doc_index
            self._search_index = index
        else:
            self._index = index
            self._search_index = DocumentSearchIndex(index)
        self._form_to_posting: Callable = form_to_posting or (lambda v: {})

        from .highlight import merge_matches

        eng = self  # capture

        def _resolve(x: str | Posting | Sentence) -> Posting | Sentence:
            if isinstance(x, str):
                return eng._to_posting(x)
            return x

        def _as_posting(x: str | Posting | Sentence) -> Posting:
            """Ensure x is a Posting — resolve str, convert forms via the hook."""
            val = _resolve(x)
            if isinstance(val, dict):
                return val
            if isinstance(val, list):
                return eng._form_to_posting(val)
            return {}

        def _and(*args: str | Posting | Sentence) -> Posting:
            sets = [_as_posting(a) for a in args]
            result = sets[0]
            for s in sets[1:]:
                result = {k: merge_matches(v, s[k]) for k, v in result.items() if k in s}
            return result

        def _or(*args: str | Posting | Sentence) -> Posting:
            sets = [_as_posting(a) for a in args]
            result = dict(sets[0])
            for s in sets[1:]:
                for k, v in s.items():
                    result[k] = merge_matches(result[k], v) if k in result else v
            return result

        def _not(*args: str | Posting | Sentence) -> Posting:
            resolved = [_as_posting(a) for a in args]
            base = resolved[0]
            for a in resolved[1:]:
                base = {k: v for k, v in base.items() if k not in a}
            return base

        def _match_doc(doc_name: str, source: str | Posting | Sentence) -> bool:
            import fnmatch

            if isinstance(source, dict):
                return (doc_name, 0) in source
            if isinstance(source, list):
                return (doc_name, 0) in _as_posting(source)
            d, p = str(doc_name), str(source)
            if "*" in p or "?" in p:
                return fnmatch.fnmatch(d, p) or fnmatch.fnmatch(d, "*/" + p)
            # Auto-glob: wrap with * so "atoms.py" matches "parseltongue/core/atoms.py"
            return fnmatch.fnmatch(d, f"*{p}*")

        def _in(source: str | Posting | Sentence, query: str | Posting | Sentence | None = None) -> Posting:
            def pred(d):
                return _match_doc(d, source)

            if query is None:
                return eng._search_index.match_docs(pred)
            posting = _as_posting(query)
            filtered = {k: v for k, v in posting.items() if pred(k[0])}
            if filtered or not posting:
                return filtered
            # Global search found results but none in the target docs.
            # Fall back: search within matching docs directly via corpus.
            if isinstance(query, str):
                from .strategy import _make_posting

                snap = eng._search_index._snap
                for doc_name, sdoc in snap.documents.items():
                    if not pred(doc_name):
                        continue
                    for line_num, line in enumerate(sdoc.lines, 1):
                        if query.lower() in line.lower():
                            filtered[(doc_name, line_num)] = _make_posting(doc_name, line_num, sdoc.lines)
            return filtered

        def _not_in(source: str | Posting | Sentence, query: str | Posting | Sentence | None = None) -> Posting:
            def pred(d):
                return not _match_doc(d, source)

            if query is None:
                return eng._search_index.match_docs(pred)
            posting = _as_posting(query)
            return {k: v for k, v in posting.items() if pred(k[0])}

        def _count(*args: str | Posting | Sentence) -> int:
            v = _resolve(args[0])
            if isinstance(v, list):
                return len(v)
            if isinstance(v, dict):
                return len(v)
            return 0

        def _near(distance: int, a: str | Posting | Sentence, b: str | Posting | Sentence) -> Posting:
            sa, sb = _as_posting(a), _as_posting(b)
            n = int(distance)
            b_by_doc: dict[str, set[int]] = {}
            for doc, line in sb:
                b_by_doc.setdefault(doc, set()).add(line)
            result: Posting = {}
            for k, v in sa.items():
                doc, line = k
                b_lines = b_by_doc.get(doc, set())
                if any(abs(line - bl) <= n for bl in b_lines):
                    result[k] = merge_matches(v, sb[k]) if k in sb else v
            return result

        def _seq(a: str | Posting | Sentence, b: str | Posting | Sentence) -> Posting:
            sa, sb = _as_posting(a), _as_posting(b)
            b_by_doc: dict[str, int] = {}
            for doc, line in sb:
                if doc not in b_by_doc or line > b_by_doc[doc]:
                    b_by_doc[doc] = line
            return {k: v for k, v in sa.items() if k[0] in b_by_doc and k[1] < b_by_doc[k[0]]}

        def _re(pattern: str, source: str | Posting | Sentence | None = None) -> Posting:
            import re as _re_mod

            rx = _re_mod.compile(pattern)
            if source is not None:
                posting = _as_posting(source)
                doc_names = {k[0] for k in posting}
            else:
                doc_names = None
            result: Posting = {}
            for doc_name, sdoc in eng._search_index.documents.items():
                if doc_names is not None and doc_name not in doc_names:
                    continue
                for i, line_text in enumerate(sdoc.lines, 1):
                    if rx.search(line_text):
                        key = (doc_name, i)
                        result[key] = {
                            "document": doc_name,
                            "line": i,
                            "column": 1,
                            "context": line_text,
                            "_match_regex": (pattern,),
                            "callers": [],
                            "total_callers": 0,
                        }
            return result

        def _lines(start: int, end: int, query: str | Posting | Sentence) -> Posting:
            posting = _as_posting(query)
            s, e = int(start), int(end)
            return {k: v for k, v in posting.items() if s <= k[1] <= e}

        def _context_lines(n: int, query: str | Posting | Sentence, before: bool = True, after: bool = True) -> Posting:
            """Expand matches to include surrounding lines."""
            posting = _as_posting(query)
            n = int(n)
            expanded = dict(posting)
            for (doc, line), _ in posting.items():
                sdoc = eng._search_index.documents.get(doc)
                if not sdoc:
                    continue
                start = max(0, line - 1 - (n if before else 0))
                end = min(len(sdoc.lines), line + (n if after else 0))
                for i in range(start, end):
                    key = (doc, i + 1)
                    if key not in expanded:
                        expanded[key] = {
                            "document": doc,
                            "line": i + 1,
                            "column": 1,
                            "context": sdoc.lines[i],
                            "callers": [],
                            "total_callers": 0,
                        }
            return expanded

        def _before(n: int, query: str | Posting | Sentence) -> Posting:
            return _context_lines(n, query, before=True, after=False)

        def _after(n: int, query: str | Posting | Sentence) -> Posting:
            return _context_lines(n, query, before=False, after=True)

        def _context(n: int, query: str | Posting | Sentence) -> Posting:
            return _context_lines(n, query, before=True, after=True)

        def _strategy(name: str, query: str | Posting | Sentence) -> Posting:
            """Explicit strategy selection: (strategy "stemmed" "query")."""
            return eng._search_index.search(str(query), strategy=str(name))

        def _rank(strategy: str, query: str | Posting | Sentence) -> Posting:
            posting = _as_posting(query)
            items = list(posting.values())
            strat = str(strategy)
            if strat == "callers":
                traced = [ln for ln in items if ln.get("callers")]
                untraced = [ln for ln in items if not ln.get("callers")]
                traced.sort(key=lambda ln: (-ln["total_callers"], -ln["callers"][0]["overlap"]))
                items = traced + untraced
            elif strat == "coverage":
                traced = [ln for ln in items if ln.get("callers")]
                untraced = [ln for ln in items if not ln.get("callers")]
                traced.sort(key=lambda ln: (-ln["callers"][0]["overlap"], -ln["total_callers"]))
                items = traced + untraced
            elif strat == "document":
                by_doc: dict[str, list[dict]] = {}
                for ln in items:
                    by_doc.setdefault(ln["document"], []).append(ln)
                doc_order = sorted(by_doc.keys(), key=lambda d: -len(by_doc[d]))
                items = []
                for doc in doc_order:
                    doc_lines = sorted(by_doc[doc], key=lambda ln: (-ln["total_callers"], ln["line"]))
                    items.extend(doc_lines)
            elif strat == "line":
                items.sort(key=lambda ln: (ln["document"], ln["line"]))
            return {(ln["document"], ln["line"]): ln for ln in items}

        def _limit(n: int, query: str | Posting | Sentence) -> Posting | Sentence:
            """Take first N entries from a posting set or form list."""
            val = _resolve(query)
            n = int(n)
            if is_sentence_list(val):
                return val[:n]
            if isinstance(val, dict):
                keys = list(val.keys())[:n]
                return {k: val[k] for k in keys}
            return val

        def _files(query: str | Posting | Sentence) -> Sentence:
            """Project a posting set (or form list) to its unique document names.

            Pure projection — preserves the iteration order of the input.
            """
            val = _resolve(query)
            seen: dict[str, None] = {}  # ordered set
            if isinstance(val, dict):
                for key in val.keys():
                    if isinstance(key, tuple) and len(key) >= 1 and isinstance(key[0], str):
                        seen.setdefault(key[0], None)
            elif isinstance(val, list):
                for entry in val:
                    if isinstance(entry, (list, tuple)) and len(entry) >= 2 and isinstance(entry[1], str):
                        seen.setdefault(entry[1], None)
            return list(seen.keys())

        self.ops: dict = {
            Symbol("and"): _and,
            Symbol("or"): _or,
            Symbol("not"): _not,
            Symbol("in"): _in,
            Symbol("not-in"): _not_in,
            Symbol("count"): _count,
            Symbol("near"): _near,
            Symbol("seq"): _seq,
            Symbol("re"): _re,
            Symbol("lines"): _lines,
            Symbol("before"): _before,
            Symbol("after"): _after,
            Symbol("context"): _context,
            Symbol("strategy"): _strategy,
            Symbol("rank"): _rank,
            Symbol("limit"): _limit,
            Symbol("files"): _files,
        }
        self.resolve = _resolve
        self.as_posting = _as_posting

        self._pltg_system = PltgSystem(initial_env=dict(self.ops), docs={}, strict_derive=False, name="QueryEngine")

    def _to_posting(self, text: str) -> Posting:
        """Default lookup: cascade strategy + quote enrichment."""
        return self._search_index.search(text)

    def refresh(self):
        """Sync the search index with the underlying DocumentIndex."""
        self._search_index.refresh(self._index)

    def evaluate_posting(self, expr: "str | Sentence") -> Posting:
        """Evaluate a query — string or form — to a posting set."""
        if isinstance(expr, str):
            if not expr.strip():
                return {}
            from parseltongue.core.lang import PGStringParser

            parsed = PGStringParser.translate(expr)
        else:
            parsed = expr
        if isinstance(parsed, str):
            return self._to_posting(parsed)
        if isinstance(parsed, (list, tuple)) and len(parsed) == 1 and isinstance(parsed[0], str):
            return self._to_posting(parsed[0])
        if isinstance(parsed, (list, tuple)) and parsed:
            head = parsed[0]
            if isinstance(head, Symbol) and head in self._pltg_system.engine.env:
                result = self._pltg_system.evaluate(parsed)
                return result if isinstance(result, dict) else {}
            return self._to_posting(str(expr))
        result = self._pltg_system.evaluate(parsed)
        return result if isinstance(result, dict) else {}


def compose_satisfies(x_form, s_form):
    """Compose a :forall pattern with its :satisfies condition.

    (near N cond) → (near N X cond); (seq cond) → (seq X cond);
    anything else → (and X cond) — same-line co-occurrence.
    """
    if isinstance(s_form, (list, tuple)) and s_form:
        head = str(s_form[0])
        if head == "near" and len(s_form) >= 3:
            return (s_form[0], s_form[1], x_form, *s_form[2:])
        if head == "seq" and len(s_form) >= 2:
            return (s_form[0], x_form, *s_form[1:])
    return (Symbol("and"), x_form, s_form)
