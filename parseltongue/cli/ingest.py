"""Document ingestion — convert any format to plain text via docling."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger('parseltongue.cli')

# Plain text extensions that don't need docling
_PLAINTEXT_EXTS = {'.txt', '.text', '.md', '.markdown'}


def ingest_file(path: str) -> str:
    """Convert a file to plain text.

    Plain text files are read directly. Everything else goes through
    docling's DocumentConverter (PDF, DOCX, PPTX, HTML, images, etc.).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if p.suffix.lower() in _PLAINTEXT_EXTS:
        log.info("Reading plain text: %s", path)
        return p.read_text(encoding='utf-8')

    log.info("Converting via docling: %s", path)
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(p))
    return result.document.export_to_markdown()


def parse_document_arg(arg: str) -> tuple[str, str]:
    """Parse a -d argument into (name, path).

    Formats:
        "name:path/to/file.pdf"  -> ("name", "path/to/file.pdf")
        "path/to/file.pdf"       -> ("file", "path/to/file.pdf")
    """
    if ':' in arg and not Path(arg).exists():
        name, path = arg.split(':', 1)
        return name.strip(), path.strip()
    p = Path(arg)
    return p.stem, str(p)
