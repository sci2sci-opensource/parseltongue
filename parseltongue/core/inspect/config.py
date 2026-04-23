"""Bench configuration — project detection, pg.toml + .pgignore generation.

Single source of truth. Config manages config — store just calls config.

Files managed:
  pg.toml   — bench settings (extensions, languages, index options)
  .pgignore — gitignore-style ignore patterns for traversal
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

from parseltongue.core.loader.files import EXT_TYPE

log = logging.getLogger("parseltongue.config")

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

# ── Parseltongue extensions (from loader/files.py — single source of truth) ───
_PARSELTONGUE_EXTENSIONS = sorted(EXT_TYPE.keys())
BASE_EXTENSIONS = [".md", ".txt"] + _PARSELTONGUE_EXTENSIONS

# ── Size guardrail defaults ───────────────────────────────────────────────────
# Files over this size are treated as anomalies during indexing: skipped and
# reported at error-level so the user must explicitly decide — either ignore
# them via .pgignore or permit them via [index].allow_large globs in pg.toml.
DEFAULT_MAX_FILE_SIZE_BYTES = 1_048_576  # 1 MB

# ── Language presets ──────────────────────────────────────────────────────────
LANGUAGE_PRESETS: dict[str, list[str]] = {
    # Parseltongue native — derived from loader/files.py
    "parseltongue": _PARSELTONGUE_EXTENSIONS,
    # General purpose
    "python": [".py", ".pyi"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx", ".mts", ".cts"],
    "rust": [".rs"],
    "go": [".go"],
    "java": [".java"],
    "kotlin": [".kt", ".kts"],
    "scala": [".scala"],
    "ruby": [".rb"],
    "php": [".php"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".hpp", ".cc", ".hh", ".cxx", ".hxx"],
    "csharp": [".cs"],
    "swift": [".swift"],
    "zig": [".zig"],
    "elixir": [".ex", ".exs"],
    "haskell": [".hs"],
    "lua": [".lua"],
    "shell": [".sh", ".bash", ".zsh"],
    "dart": [".dart"],
    "r": [".r", ".R", ".Rmd"],
    "objc": [".m", ".mm"],
    "groovy": [".groovy", ".gvy", ".gy"],
    "clojure": [".clj", ".cljs", ".cljc", ".edn"],
    "erlang": [".erl", ".hrl"],
    "ocaml": [".ml", ".mli"],
    "fsharp": [".fs", ".fsi", ".fsx"],
    "julia": [".jl"],
    "perl": [".pl", ".pm"],
    "nim": [".nim", ".nims"],
    "solidity": [".sol"],
    "v": [".v"],
    "crystal": [".cr"],
    "d": [".d"],
    "fortran": [".f90", ".f95", ".f03", ".f08", ".f", ".for"],
    "ada": [".adb", ".ads"],
    "pascal": [".pas", ".pp"],
    "lisp": [".lisp", ".lsp", ".cl"],
    "scheme": [".scm", ".ss"],
    "racket": [".rkt"],
    "elm": [".elm"],
    "purescript": [".purs"],
    "reasonml": [".re", ".rei"],
    "coffeescript": [".coffee"],
    "powershell": [".ps1", ".psm1", ".psd1"],
    # Statistical / scientific
    "sas": [".sas"],
    "stata": [".do", ".ado"],
    "spss": [".sps"],
    "matlab": [".m", ".mlx"],
    "mathematica": [".wl", ".nb"],
    # Bioinformatics pipelines
    "nextflow": [".nf"],
    "snakemake": [".smk"],
    "wdl": [".wdl"],
    "cwl": [".cwl"],
    # Notebooks
    "jupyter": [".ipynb"],
    # HDL / hardware
    "verilog": [".v", ".sv", ".svh"],
    "vhdl": [".vhd", ".vhdl"],
    # Infrastructure / config
    "terraform": [".tf", ".tfvars"],
    "docker": [".dockerfile"],
    "nix": [".nix"],
    "proto": [".proto"],
    "ansible": [".ansible.yml"],
    "puppet": [".pp"],
    "cmake": [".cmake"],
    "make": [".mk"],
    "bazel": [".bzl", ".bazel"],
    # Config languages
    "jsonnet": [".jsonnet", ".libsonnet"],
    "cue": [".cue"],
    "dhall": [".dhall"],
    "kdl": [".kdl"],
    # Templating
    "jinja": [".jinja", ".jinja2", ".j2"],
    "handlebars": [".hbs", ".handlebars"],
    "ejs": [".ejs"],
    "pug": [".pug"],
    "erb": [".erb"],
    # API / schema
    "thrift": [".thrift"],
    "avro": [".avsc"],
    "flatbuffers": [".fbs"],
    "capnproto": [".capnp"],
    # Data / markup
    "sql": [".sql"],
    "html": [".html", ".htm"],
    "css": [".css"],
    "sass": [".scss", ".sass"],
    "less": [".less"],
    "yaml": [".yml", ".yaml"],
    "toml": [".toml"],
    "json": [".json"],
    "graphql": [".graphql", ".gql"],
    "xml": [".xml", ".xsl", ".xslt", ".xsd"],
    "csv": [".csv", ".tsv"],
    "rst": [".rst"],
    "asciidoc": [".adoc", ".asciidoc"],
    "latex": [".tex", ".sty", ".cls"],
    "mdx": [".mdx"],
    "quarto": [".qmd"],
    "orgmode": [".org"],
    "diff": [".diff", ".patch"],
    # Frontend frameworks
    "svelte": [".svelte"],
    "vue": [".vue"],
    "astro": [".astro"],
}

# ── Binary extensions (never index) ───────────────────────────────────────────
BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".svg",
        ".webp",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".webm",
        ".avi",
        ".mov",
        ".zip",
        ".gz",
        ".tar",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".lib",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".pyc",
        ".pyo",
        ".class",
        ".jar",
        ".war",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".bin",
        ".dat",
        ".pak",
    }
)

# ── Default ignore patterns (hardcoded floor) ────────────────────────────────
DEFAULT_IGNORE = [".git", ".hg", ".svn", "node_modules", ".*"]

# ── Extension → language (inverted from LANGUAGE_PRESETS) ─────────────────────


def _build_ext_to_langs() -> tuple[dict[str, list[str]], list[tuple[str, list[str]]]]:
    """Build extension→language map. Returns (simple_map, compound_list).

    Compound extensions (e.g. .ansible.yml, .pg.md) have >1 dot and need
    endswith() matching since Path.suffix only returns the last segment.
    """
    simple: dict[str, list[str]] = {}
    compound: list[tuple[str, list[str]]] = []
    for lang, exts in LANGUAGE_PRESETS.items():
        for ext in exts:
            if ext.count(".") > 1:
                compound.append((ext, [lang]))
            else:
                simple.setdefault(ext, []).append(lang)
    return simple, compound


_EXT_TO_LANGS, _COMPOUND_EXTS = _build_ext_to_langs()

# ── Ignore patterns per language ──────────────────────────────────────────────
_LANGUAGE_IGNORES: dict[str, list[str]] = {
    "python": [
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        "*.egg-info/",
        "dist/",
        "build/",
        ".venv/",
        "venv/",
        ".tox/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".ruff_cache/",
    ],
    "javascript": ["node_modules/", "dist/", "build/", ".next/", ".nuxt/", "coverage/"],
    "typescript": ["node_modules/", "dist/", "build/", ".next/", ".nuxt/", "coverage/"],
    "rust": ["target/"],
    "go": ["vendor/"],
    "java": ["target/", "build/", ".gradle/", "*.class"],
    "kotlin": ["target/", "build/", ".gradle/", "*.class"],
    "scala": ["target/", ".bsp/"],
    "ruby": ["vendor/", ".bundle/"],
    "php": ["vendor/"],
    "c": ["*.o", "*.a", "*.so", "*.dylib", "build/"],
    "cpp": ["*.o", "*.a", "*.so", "*.dylib", "build/"],
    "csharp": ["bin/", "obj/"],
    "swift": [".build/", ".swiftpm/"],
    "zig": ["zig-cache/", "zig-out/"],
    "elixir": ["_build/", "deps/"],
    "haskell": [".stack-work/", "dist-newstyle/"],
    "terraform": [".terraform/", "*.tfstate", "*.tfstate.backup"],
    "docker": [],
    "nix": ["result"],
    "dart": [".dart_tool/", ".packages", "build/", ".pub-cache/"],
    "r": [".Rhistory", ".RData", ".Rproj.user/"],
    "objc": ["build/", "DerivedData/", "*.o"],
    "groovy": ["build/", ".gradle/", "*.class"],
    "clojure": ["target/", ".cpcache/", ".nrepl-port"],
    "erlang": ["_build/", "deps/", "*.beam"],
    "ocaml": ["_build/", "*.cmi", "*.cmo", "*.cmx", "*.o"],
    "fsharp": ["bin/", "obj/"],
    "julia": [".julia/"],
    "perl": ["blib/", "_build/", "*.o"],
    "nim": ["nimcache/", "nimblecache/"],
    "solidity": ["artifacts/", "cache/", "node_modules/"],
    "v": [],
    "crystal": ["lib/", ".crystal/"],
    "d": [".dub/", "*.o", "*.di"],
    "fortran": ["*.mod", "*.o"],
    "ada": ["*.ali", "*.o", "obj/"],
    "pascal": ["*.o", "*.ppu", "lib/"],
    "lisp": [],
    "scheme": [],
    "racket": ["compiled/"],
    "elm": ["elm-stuff/"],
    "purescript": ["output/", ".spago/", "bower_components/"],
    "reasonml": ["_build/", "node_modules/", ".merlin"],
    "coffeescript": ["node_modules/"],
    "powershell": [],
    "cmake": ["build/", "CMakeFiles/", "CMakeCache.txt"],
    "make": [],
    "bazel": ["bazel-*/"],
    "svelte": ["node_modules/", ".svelte-kit/", "build/"],
    "vue": ["node_modules/", "dist/"],
    "astro": ["node_modules/", "dist/"],
    "latex": ["*.aux", "*.log", "*.toc", "*.out", "*.bbl", "*.blg", "*.synctex.gz", "*.fls", "*.fdb_latexmk"],
    "sas": ["*.log", "*.lst", "*.sas7bdat"],
    "stata": ["*.log", "*.smcl", "*.gph"],
    "spss": ["*.spo", "*.spv"],
    "matlab": ["*.mex*", "*.asv", "*.slxc"],
    "mathematica": [".MathematicaCache/"],
    "nextflow": [".nextflow/", ".nextflow.log*", "work/"],
    "snakemake": [".snakemake/"],
    "wdl": ["cromwell-executions/", "cromwell-workflow-logs/"],
    "jupyter": [".ipynb_checkpoints/"],
    "verilog": ["*.vvp", "*.vcd"],
    "vhdl": ["*.cf", "work/"],
}

_PGIGNORE_HEADER = [
    "# Parseltongue bench ignore file (auto-generated by pg-bench init)",
    "# gitignore-style patterns — one per line",
    "",
    "# Version control",
    ".git/",
    ".hg/",
    ".svn/",
    "",
    "# OS / editor",
    ".DS_Store",
    "Thumbs.db",
    "*.swp",
    "*.swo",
    ".idea/",
    ".vscode/",
    "",
    "# Bench cache",
    ".parseltongue-bench/",
]


# ── Detection ─────────────────────────────────────────────────────────────────


def detect_languages(
    directory: str | Path | None = None,
    depth: int = 6,
    *,
    use_gitignore_prune: bool = True,
) -> list[str]:
    """Detect project languages by scanning for file extensions.

    Walks ``directory`` to ``depth`` levels (default 6 — deep enough for nested
    multi-repo workspaces like xen / vcstool / google repo, where actual source
    lives 3-5 levels below the workspace root).

    If ``use_gitignore_prune`` is True (default), reads ``.gitignore`` and adds
    its simple directory patterns to the prune set, avoiding walks into build
    artifacts, venvs, node_modules etc. Set to False for orchestrated workspaces
    where ``.gitignore`` deliberately hides nested git repos that ARE the project
    (xen, vcstool) — otherwise detection silently misses everything inside them.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    found: set[str] = set()
    seen_exts: set[str] = set()

    # Hardcoded prune floor — these are never useful to walk regardless of mode
    skip_dirs: set[str] = {"node_modules", "__pycache__", "vendor", "target", ".git"}
    if use_gitignore_prune:
        gi_patterns = _read_gitignore(d)
        for pat in gi_patterns:
            # Simple directory patterns (e.g. "venv", "dist/", "build/") → add to skip set
            clean = pat.rstrip("/").lstrip("/")
            if "/" not in clean and "*" not in clean:
                skip_dirs.add(clean)

    def _scan(path: Path, level: int):
        if level > depth:
            return
        try:
            entries = list(path.iterdir())
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file():
                name = entry.name.lower()
                # Skip config files generated by bench itself
                if name in ("pg.toml", ".pgignore"):
                    continue
                # Check compound extensions first (e.g. .ansible.yml, .pg.md)
                for cext, clangs in _COMPOUND_EXTS:
                    if name.endswith(cext):
                        found.update(clangs)
                        break
                ext = entry.suffix.lower()
                if ext and ext not in seen_exts:
                    seen_exts.add(ext)
                    langs = _EXT_TO_LANGS.get(ext)
                    if langs:
                        found.update(langs)
            elif entry.is_dir() and level < depth:
                if entry.name in skip_dirs:
                    continue
                _scan(entry, level + 1)

    _scan(d, 0)
    return sorted(found) if found else ["python"]


def extensions_for(languages: list[str]) -> list[str]:
    """Build sorted, deduplicated extension list for the given languages."""
    exts = set(BASE_EXTENSIONS)
    for lang in languages:
        exts.update(LANGUAGE_PRESETS.get(lang, []))
    return sorted(exts)


# ── .pgignore generation ─────────────────────────────────────────────────────


def _read_gitignore(directory: Path) -> list[str]:
    """Read .gitignore patterns (skip comments/blanks)."""
    gi = directory / ".gitignore"
    if not gi.exists():
        return []
    return [line.strip() for line in gi.read_text().splitlines() if line.strip() and not line.strip().startswith("#")]


def generate_pgignore(
    directory: str | Path | None = None,
    *,
    absorb_gitignore: bool = True,
) -> str:
    """Generate .pgignore content.

    With ``absorb_gitignore=True`` (default), copies the project's ``.gitignore``
    patterns into the output under a ``# From .gitignore`` block. This is the
    right default for the common single-repo case where ``.gitignore`` represents
    "files I don't care about".

    Set ``absorb_gitignore=False`` for orchestrated multi-repo workspaces (xen,
    vcstool, google repo) where ``.gitignore`` deliberately hides nested child
    repos that ARE the project. Absorbing it would skip everything you wanted
    to index.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    languages = detect_languages(d, use_gitignore_prune=absorb_gitignore)
    lines = list(_PGIGNORE_HEADER)

    gi_patterns: list[str] = []
    if absorb_gitignore:
        gi_patterns = _read_gitignore(d)
        if gi_patterns:
            lines.append("")
            lines.append("# From .gitignore")
            lines.extend(gi_patterns)

    seen: set[str] = set(gi_patterns)
    for lang in languages:
        lang_ignores = _LANGUAGE_IGNORES.get(lang, [])
        new = [p for p in lang_ignores if p not in seen]
        if new:
            lines.append("")
            lines.append(f"# {lang.title()}")
            lines.extend(new)
            seen.update(new)

    lines.append("")
    return "\n".join(lines)


# ── pg.toml generation ────────────────────────────────────────────────────────


def _toml_list(items: list[str]) -> str:
    """Format a Python list as a TOML array."""
    inner = ", ".join(f'"{item}"' for item in items)
    return f"[{inner}]"


def generate_pg_toml(
    directory: str | Path | None = None,
    *,
    use_gitignore_prune: bool = True,
) -> str:
    """Generate pg.toml content based on project detection.

    See ``detect_languages`` for the meaning of ``use_gitignore_prune``.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    languages = detect_languages(d, use_gitignore_prune=use_gitignore_prune)
    extensions = extensions_for(languages)

    lines = [
        "# Parseltongue bench config (auto-generated by pg-bench init)",
        "",
        "[detect]",
        f"languages = {_toml_list(languages)}",
        "",
        "[index]",
        f"extensions = {_toml_list(extensions)}",
        "",
        "# Size guardrail: files over this size are skipped during indexing",
        "# and reported at error-level. Every oversized file must be either",
        "# .pgignore'd or explicitly allowed via allow_large below.",
        f"max_file_size_bytes = {DEFAULT_MAX_FILE_SIZE_BYTES}",
        "allow_large = []",
        "",
    ]
    return "\n".join(lines)


# ── Config API ────────────────────────────────────────────────────────────────

_init_lock = threading.Lock()


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, content.encode())
        os.close(fd)
        closed = True
        os.replace(tmp, path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_initialized(directory: str | Path | None = None) -> bool:
    """True if pg.toml exists in directory."""
    d = Path(directory) if directory is not None else Path(os.getcwd())
    return (d / "pg.toml").exists()


def load_config(directory: str | Path | None = None) -> dict:
    """Load pg.toml from directory. Returns parsed dict."""
    d = Path(directory) if directory is not None else Path(os.getcwd())
    path = d / "pg.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_extensions(directory: str | Path | None = None) -> list[str]:
    """Load extensions from pg.toml. Auto-inits config if missing."""
    d = Path(directory) if directory is not None else Path(os.getcwd())
    ensure_initialized(d)
    conf = load_config(d)
    return list(conf.get("index", {}).get("extensions", BASE_EXTENSIONS))


def load_max_file_size_bytes(directory: str | Path | None = None) -> int:
    """Load the index size guardrail threshold from pg.toml.

    Files larger than this are skipped during indexing and reported at
    error-level so the user must resolve them explicitly (ignore or allow).
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    ensure_initialized(d)
    conf = load_config(d)
    return int(conf.get("index", {}).get("max_file_size_bytes", DEFAULT_MAX_FILE_SIZE_BYTES))


def load_allow_large_globs(directory: str | Path | None = None) -> list[str]:
    """Load gitignore-style globs of oversized files to index anyway.

    Each entry matches paths relative to the indexed directory, using the
    same matcher as .pgignore.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    ensure_initialized(d)
    conf = load_config(d)
    return list(conf.get("index", {}).get("allow_large", []))


def load_ignore_patterns(directory: str | Path | None = None) -> list[str]:
    """Load ignore patterns. DEFAULT_IGNORE + .pgignore lines."""
    d = Path(directory) if directory is not None else Path(os.getcwd())
    ensure_initialized(d)
    patterns = list(DEFAULT_IGNORE)
    pgignore = d / ".pgignore"
    if pgignore.exists():
        for line in pgignore.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
    return patterns


_migrated_dirs: set[Path] = set()


def _migrate_index_guardrails(directory: Path) -> bool:
    """Append size-guardrail keys to an existing pg.toml if they're missing.

    This is a one-time migration for projects whose pg.toml predates the
    [index].max_file_size_bytes / allow_large keys. Idempotent: the parsed
    [index] section is inspected, so user-edited values are never
    overwritten. Returns True iff the file was modified.

    Process-level cache keyed on the directory prevents repeated parsing
    on hot config-loader paths.
    """
    if directory in _migrated_dirs:
        return False
    path = directory / "pg.toml"
    if not path.exists():
        _migrated_dirs.add(directory)
        return False
    try:
        conf = load_config(directory)
    except Exception:
        _migrated_dirs.add(directory)
        return False
    index_section = conf.get("index", {})
    missing_lines: list[str] = []
    if "max_file_size_bytes" not in index_section:
        missing_lines.extend(
            [
                "",
                "# Size guardrail: files over this size are skipped during indexing",
                "# and reported at error-level. Every oversized file must be either",
                "# .pgignore'd or explicitly allowed via allow_large below.",
                f"max_file_size_bytes = {DEFAULT_MAX_FILE_SIZE_BYTES}",
            ]
        )
    if "allow_large" not in index_section:
        missing_lines.append("allow_large = []")
    if not missing_lines:
        _migrated_dirs.add(directory)
        return False
    existing = path.read_text()
    suffix = ("" if existing.endswith("\n") else "\n") + "\n".join(missing_lines) + "\n"
    _atomic_write(path, existing + suffix)
    _migrated_dirs.add(directory)
    return True


def ensure_initialized(directory: str | Path | None = None) -> None:
    """If pg.toml or .pgignore is missing, generate and write them.

    Also migrates existing pg.toml files that predate the size-guardrail
    keys, appending default values and logging the change so users know.

    Thread-safe: uses a lock so concurrent callers wait rather than
    racing to generate config simultaneously. Writes are atomic
    (temp file + rename) so readers never see partial content.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    if (d / "pg.toml").exists() and (d / ".pgignore").exists():
        # Fast path — both files exist. Still check for guardrail migration
        # once per directory (cached in _migrated_dirs so hot callers pay
        # only the set-lookup cost).
        if d not in _migrated_dirs:
            with _init_lock:
                if _migrate_index_guardrails(d):
                    log.warning(
                        "Migrated pg.toml at %s: appended default size guardrail "
                        "(max_file_size_bytes=%d, allow_large=[]). Review and "
                        "adjust if needed.",
                        d,
                        DEFAULT_MAX_FILE_SIZE_BYTES,
                    )
        return
    with _init_lock:
        # Re-check under lock (another thread may have written while we waited)
        if not (d / "pg.toml").exists():
            _atomic_write(d / "pg.toml", generate_pg_toml(d))
        if not (d / ".pgignore").exists():
            _atomic_write(d / ".pgignore", generate_pgignore(d))
        # Also migrate if pg.toml was pre-existing when we entered the lock
        _migrate_index_guardrails(d)


def _append_missing_lines(path: Path, new_content: str) -> bool:
    """Append lines from new_content that don't already exist in path.

    Returns True if anything was appended.
    """
    existing = path.read_text() if path.exists() else ""
    existing_lines = set(
        line.strip() for line in existing.splitlines() if line.strip() and not line.strip().startswith("#")
    )
    new_lines = []
    for line in new_content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped not in existing_lines:
            new_lines.append(line)
    if not new_lines:
        return False
    # Append with a separator
    suffix = "\n" if not existing.endswith("\n") else ""
    suffix += "\n# Auto-appended by pg-bench init\n"
    suffix += "\n".join(new_lines) + "\n"
    _atomic_write(path, existing + suffix)
    return True


# Modes: "skip" (don't touch if exists), "force" (overwrite), "append" (add missing)
InitMode = str  # "skip" | "force" | "append"


def init(
    directory: str | Path | None = None,
    toml_mode: InitMode = "skip",
    pgignore_mode: InitMode = "skip",
    *,
    absorb_gitignore: bool = True,
) -> dict:
    """Full init: detect project, write pg.toml + .pgignore, return report.

    Thread-safe. Modes per file:
      "skip"   — don't touch if exists (default)
      "force"  — overwrite entirely
      "append" — add missing entries to existing file

    ``absorb_gitignore`` controls both:
      - Whether ``.gitignore`` lines are copied into the generated ``.pgignore``
      - Whether ``.gitignore`` patterns are used to prune the language-detection walk
    Default True (single-repo project where .gitignore == "skip these").
    Pass False for orchestrated multi-repo workspaces (xen, vcstool, google repo)
    where .gitignore hides nested children that ARE the project.
    """
    d = Path(directory) if directory is not None else Path(os.getcwd())
    with _init_lock:
        languages = detect_languages(d, use_gitignore_prune=absorb_gitignore)
        extensions = extensions_for(languages)

        toml_path = d / "pg.toml"
        pgignore_path = d / ".pgignore"

        def _toml() -> str:
            return generate_pg_toml(d, use_gitignore_prune=absorb_gitignore)

        def _pgignore() -> str:
            return generate_pgignore(d, absorb_gitignore=absorb_gitignore)

        # pg.toml
        if not toml_path.exists():
            _atomic_write(toml_path, _toml())
            toml_action = "created"
        elif toml_mode == "force":
            _atomic_write(toml_path, _toml())
            toml_action = "overwritten"
        elif toml_mode == "append":
            changed = _append_missing_lines(toml_path, _toml())
            toml_action = "appended" if changed else "unchanged"
        else:
            toml_action = "skipped"

        # .pgignore
        if not pgignore_path.exists():
            _atomic_write(pgignore_path, _pgignore())
            pgignore_action = "created"
        elif pgignore_mode == "force":
            _atomic_write(pgignore_path, _pgignore())
            pgignore_action = "overwritten"
        elif pgignore_mode == "append":
            changed = _append_missing_lines(pgignore_path, _pgignore())
            pgignore_action = "appended" if changed else "unchanged"
        else:
            pgignore_action = "skipped"

    return {
        "languages": languages,
        "extensions": extensions,
        "pg_toml": str(toml_path),
        "pgignore": str(pgignore_path),
        "toml_action": toml_action,
        "pgignore_action": pgignore_action,
        "absorb_gitignore": absorb_gitignore,
    }
