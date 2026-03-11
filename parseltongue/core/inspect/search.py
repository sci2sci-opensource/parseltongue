"""Search — full-text search across loaded documents with pltg provenance tracing.

Ranking strategies:
    callers   — lines with most pltg nodes quoting them first (default)
    coverage  — lines where query best overlaps a quote range first
    document  — group by document, most hits per document first
"""

from __future__ import annotations

from enum import StrEnum

from parseltongue.core.quote_verifier.index import DocumentIndex


class Ranking(StrEnum):
    CALLERS = "callers"
    COVERAGE = "coverage"
    DOCUMENT = "document"


class Search:
    """Full-text search composed with quote provenance.

    Initialized with a DocumentIndex (from engine._verifier.index).
    Finds text across all indexed documents, then traces which pltg nodes
    quote the matched regions.
    """

    def __init__(self, index: DocumentIndex):
        self._index = index

    def query(
        self,
        text: str,
        max_lines: int = 20,
        max_callers: int = 5,
        offset: int = 0,
        rank: Ranking | str = Ranking.CALLERS,
    ) -> dict:
        """Search for text across all documents.

        Returns::

            {
                "total_lines": int,
                "total_callers": int,
                "offset": int,
                "lines": [...]
            }

        Each line: {document, line, column, context, callers, total_callers}.
        ``callers`` is a list of {name, overlap}, capped at max_callers.

        Ranking:
            callers  — most pltg callers first, then untraced
            coverage — best quote overlap first, then untraced
            document — grouped by document (most total hits first), lines in order
        """
        rank = Ranking(rank)
        all_lines, all_callers = self._collect(text, max_lines + offset, max_callers)
        ranked = self._rank(all_lines, rank)[offset : offset + max_lines]

        return {
            "total_lines": len(all_lines),
            "total_callers": len(all_callers),
            "offset": offset,
            "lines": ranked,
        }

    def _collect(self, text: str, max_lines: int, max_callers: int):
        """Collect all matching lines with their callers."""
        idx = self._index

        doc_hits = idx.search(text)
        traced = idx.trace(text)

        # Group callers by (document, line)
        callers_by_line: dict[tuple[str, int], dict[str, dict]] = {}
        all_callers: set[str] = set()
        for r in traced:
            key = (r["document"], r["line"])
            name = r["caller"]
            all_callers.add(name)
            by_name = callers_by_line.setdefault(key, {})
            if name not in by_name or r["overlap"] > by_name[name]["overlap"]:
                by_name[name] = {"name": name, "overlap": r["overlap"]}

        # Build unified line list
        seen: set[tuple[str, int]] = set()
        lines = []

        # Traced lines
        for r in traced:
            key = (r["document"], r["line"])
            if key in seen:
                continue
            seen.add(key)
            callers = sorted(callers_by_line[key].values(), key=lambda c: -c["overlap"])
            lines.append(
                {
                    "document": r["document"],
                    "line": r["line"],
                    "column": r.get("column", 1),
                    "context": r["context"],
                    "callers": callers,
                    "total_callers": len(callers),
                }
            )

        # Untraced doc hits
        for hit in doc_hits:
            key = (hit["document"], hit["line"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                {
                    "document": hit["document"],
                    "line": hit["line"],
                    "column": hit.get("column", 1),
                    "context": hit["context"],
                    "callers": [],
                    "total_callers": 0,
                }
            )

        return lines, all_callers

    def _rank(self, lines: list[dict], rank: Ranking) -> list[dict]:
        if rank == Ranking.CALLERS:
            return self._rank_by_callers(lines)
        elif rank == Ranking.COVERAGE:
            return self._rank_by_coverage(lines)
        elif rank == Ranking.DOCUMENT:
            return self._rank_by_document(lines)
        return lines

    def _rank_by_callers(self, lines: list[dict]) -> list[dict]:
        """Most pltg callers first, then untraced lines."""
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["total_callers"], -ln["callers"][0]["overlap"]))
        return traced + untraced

    def _rank_by_coverage(self, lines: list[dict]) -> list[dict]:
        """Best quote overlap first, then untraced lines."""
        traced = [ln for ln in lines if ln["callers"]]
        untraced = [ln for ln in lines if not ln["callers"]]
        traced.sort(key=lambda ln: (-ln["callers"][0]["overlap"], -ln["total_callers"]))
        return traced + untraced

    def _rank_by_document(self, lines: list[dict]) -> list[dict]:
        """Group by document, most hits per document first, lines in order within."""
        by_doc: dict[str, list[dict]] = {}
        for ln in lines:
            by_doc.setdefault(ln["document"], []).append(ln)
        # Sort documents by total hits descending
        doc_order = sorted(by_doc.keys(), key=lambda d: -len(by_doc[d]))
        result = []
        for doc in doc_order:
            # Within document: traced first, then by line number
            doc_lines = sorted(by_doc[doc], key=lambda ln: (-ln["total_callers"], ln["line"]))
            result.extend(doc_lines)
        return result
