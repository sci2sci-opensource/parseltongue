"""
General-purpose operators for the data governance demo.

Four effects registered in the System engine env:
  (csv-rows doc-name prefix)     — parse loaded CSV doc → tagged row lists
  (regex-match pattern text)     — all regex matches → list of strings or false
  (list-tree-paths pattern)      — list loaded document names matching glob
  (doc-text pattern)             — concatenated text of all docs matching glob

Effects receive (system, *args) — the System auto-wraps them.
"""

import csv
import fnmatch
import io
import re

from parseltongue.core.atoms import Symbol


def csv_rows(system, doc_name, prefix):
    """(csv-rows doc-name prefix) → ((prefix col1 col2 ...) ...)

    Reads a loaded CSV document and returns each row as a tagged list.
    The prefix becomes a Symbol — e.g. (csv-rows "tech:clinical" "dx")
    returns ((dx "DS-7570" "Phase I Safety Trials" ...) ...).
    """
    doc_name = str(doc_name)
    prefix = str(prefix)

    content = system.engine.documents.get(doc_name, "")
    if not content:
        return []

    reader = csv.DictReader(io.StringIO(content))
    tag = Symbol(prefix)
    result = []
    for row in reader:
        result.append([tag] + list(row.values()))
    return result


def regex_match(system, pattern, text):
    """(regex-match pattern text) → list of all matches, or false

    Variadic: returns ALL matches, not just the first.
    If the pattern has groups, returns the first group from each match.
    Otherwise returns the full match string from each.
    Returns false if no matches at all.

    (regex-match "DS-\\d+" "covers DS-1488 and DS-6408") → ("DS-1488" "DS-6408")
    (regex-match "(\\d+) days" "retain 90 days") → ("90")
    """
    pattern = str(pattern)
    text = str(text)

    try:
        matches = list(re.finditer(pattern, text))
    except re.error:
        # Pattern contains unescaped regex metacharacters — retry as literal
        matches = list(re.finditer(re.escape(pattern), text))
    if not matches:
        return False

    has_groups = matches[0].lastindex is not None and matches[0].lastindex > 0
    if has_groups:
        return [m.group(1) for m in matches]
    return [m.group(0) for m in matches]


def list_tree_paths(system, pattern):
    """(list-tree-paths pattern) → ("doc-name1" "doc-name2" ...)

    Lists loaded document names matching a glob pattern.
    E.g. (list-tree-paths "tech:*") → ("tech:clinical" "tech:discovery" ...)
    """
    pattern = str(pattern)
    result = []
    for name in sorted(system.engine.documents.keys()):
        if fnmatch.fnmatch(name, pattern):
            result.append(name)
    return result


def doc_text(system, pattern):
    """(doc-text pattern) → concatenated text of all docs matching glob, or false

    Reads loaded documents matching a glob pattern and returns their
    concatenated content.  Useful for cross-document regex searches.
    E.g. (regex-match "DS-1488" (doc-text "contract:*"))
    """
    pattern = str(pattern)
    parts = []
    for name in sorted(system.engine.documents.keys()):
        if fnmatch.fnmatch(name, pattern):
            parts.append(system.engine.documents[name])
    return "\n".join(parts) if parts else False


def s(system, name):
    """(s name) → resolve string as symbol via engine._eval.

    Converts a string to a Symbol and evaluates it through the engine,
    so stain/vital instrumentation captures the resolution edge.
    """
    return system.engine._eval(Symbol(str(name)), system.engine.env)


# Convenience: all effects as a dict for System(effects=...)
GOVERNANCE_EFFECTS = {
    "csv-rows": csv_rows,
    "regex-match": regex_match,
    "list-tree-paths": list_tree_paths,
    "doc-text": doc_text,
    "s": s,
}
