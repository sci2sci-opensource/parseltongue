"""Document ingestion — convert any format to plain text via docling."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("parseltongue.cli")

# Extensions read as plain text
_PLAINTEXT_EXTS = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".rst",
    ".org",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".go",
    ".rs",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".sql",
    ".r",
    ".m",
    ".pl",
    ".lua",
    ".hs",
    ".ex",
    ".exs",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".less",
    ".sass",
    ".tex",
    ".bib",
    ".rtf",
}

# Filenames (no extension) recognized as text
_PLAINTEXT_NAMES = {
    "license",
    "licence",
    "readme",
    "changelog",
    "changes",
    "authors",
    "contributors",
    "copying",
    "notice",
    "todo",
    "news",
    "history",
    "makefile",
    "dockerfile",
    "gemfile",
    "rakefile",
    "procfile",
    "vagrantfile",
    "brewfile",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".editorconfig",
    ".env",
    ".env.example",
    ".flake8",
    ".pylintrc",
    ".prettierrc",
    ".eslintrc",
}


def _is_plaintext(p: Path) -> bool:
    """Check if a file should be read as plain text."""
    if p.suffix.lower() in _PLAINTEXT_EXTS:
        return True
    if p.name.lower() in _PLAINTEXT_NAMES:
        return True
    return False


def ingest_file(path: str) -> str:
    """Convert a file to plain text.

    Known plain text formats are read directly. Rich document formats
    (PDF, DOCX, etc.) go through docling. Unknown formats are rejected.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if _is_plaintext(p):
        log.info("Reading plain text: %s", path)
        return p.read_text(encoding="utf-8")

    # Try docling for rich document formats
    try:
        log.info("Converting via docling: %s", path)
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(str(p))
        return result.document.export_to_markdown()
    except Exception as exc:
        raise ValueError(f"Unsupported document format: {p.name} ({exc})") from exc


def parse_document_arg(arg: str) -> tuple[str, str]:
    """Parse a -d argument into (name, path).

    Formats:
        "name:path/to/file.pdf"  -> ("name", "path/to/file.pdf")
        "path/to/file.pdf"       -> ("file", "path/to/file.pdf")
    """
    if ":" in arg and not Path(arg).exists():
        name, path = arg.split(":", 1)
        return name.strip(), path.strip()
    p = Path(arg)
    return p.stem, str(p)
