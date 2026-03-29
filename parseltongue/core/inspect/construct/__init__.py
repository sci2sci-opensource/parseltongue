"""The Construct — two modes, one place.

Scripts are for agents. Scenarios are for humans.

"I know kung fu." — Neo
"""

from pathlib import Path

from parseltongue.core.loader.files import file_type, is_renderable

_CONSTRUCT = Path(__file__).parent
_SCRIPTS = _CONSTRUCT / "scripts"
_SCENARIOS = _CONSTRUCT / "scenarios"

# ── Topic registry ──
# Maps topic slug → metadata.  Scripts and scenarios are discovered from
# the filesystem and attached to their topic.
#
# description: shown in the construct table
# script:      filename in scripts/ (or None)
# scenario:    filename in scenarios/ (or None)

TOPICS = {
    "white-rabbit": {
        "description": "Introduction — what Parseltongue is and why it exists",
    },
    "kung-fu": {
        "description": "Bench mastery — inspection, search, lens, diagnosis",
    },
    "to-connect": {
        "description": "pgmd notebooks — prose wired through with truth",
    },
    "dodge-bullets": {
        "description": "Screening, diagnostics, consistency",
    },
    "jump-program": {
        "description": "Resolving dynamic refs, building consistent graphs",
    },
    "no-spoon-bending": {
        "description": "Effects, verify_manual, bending accepted terms",
    },
    "read-the-code": {
        "description": "Grounding layer — documents and data to facts and axioms",
    },
    "about-matrix": {
        "description": "Systems, composition, fundamental language",
    },
    "the-truth": {
        "description": "Epistemics, std lib, grounding module, diffs",
    },
    "to-exit": {
        "description": "Scoping, projection, delegates",
    },
    "to-fly": {
        "description": "Graph navigation, search, cross-navigation",
    },
}


# ── Auto-discovery ──


def _extract_frontmatter(path: Path) -> dict[str, str]:
    """Extract YAML-ish frontmatter (name, description) from a file."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def _discover_scripts() -> dict[str, tuple[str, str]]:
    """Scan scripts/ for files with frontmatter.

    Uses ``alias`` as the topic slug, falling back to ``name``.
    ``name`` is the skill identifier (what ``pg learn`` uses);
    ``alias`` is the construct topic slug.
    """
    found: dict[str, tuple[str, str]] = {}
    if not _SCRIPTS.exists():
        return found
    for f in sorted(_SCRIPTS.iterdir()):
        if f.name.startswith(".") or not f.is_file():
            continue
        ft = file_type(f.name)
        if ft is None:
            continue
        fm = _extract_frontmatter(f)
        slug = fm.get("alias") or fm.get("name")
        if not slug:
            continue
        desc = fm.get("description", "")
        found[slug] = (f.name, desc)
    return found


def _discover_scenarios() -> dict[str, tuple[str, str]]:
    """Scan scenarios/ for renderable files (.pgmd, .pg.md, .md)."""
    found: dict[str, tuple[str, str]] = {}
    if not _SCENARIOS.exists():
        return found
    for f in sorted(_SCENARIOS.iterdir()):
        if f.name.startswith(".") or not f.is_file():
            continue
        if not is_renderable(f.name):
            continue
        # Derive slug from filename: INTRO_WHITE-RABBIT.pg.md → white-rabbit
        stem = f.name
        # Strip known extensions
        for ext in (".pg.md", ".pgmd", ".md"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        # Strip prefix up to underscore (INTRO_WHITE-RABBIT → WHITE-RABBIT)
        if "_" in stem:
            stem = stem.split("_", 1)[1]
        slug = stem.lower()
        # Description from topic registry or frontmatter
        fm = _extract_frontmatter(f)
        desc = fm.get("description", "")
        found[slug] = (f.name, desc)
    return found


def _build_registry():
    """Attach discovered scripts and scenarios to topics."""
    scripts = _discover_scripts()
    scenarios = _discover_scenarios()

    for slug, topic in TOPICS.items():
        if slug in scripts:
            topic["script"] = scripts[slug][0]
            # Prefer frontmatter description if topic has none
            if not topic.get("description"):
                topic["description"] = scripts[slug][1]
        if slug in scenarios:
            topic["scenario"] = scenarios[slug][0]

    # Add any discovered items not yet in TOPICS
    for slug, (filename, desc) in scripts.items():
        if slug not in TOPICS:
            TOPICS[slug] = {"description": desc, "script": filename}
    for slug, (filename, desc) in scenarios.items():
        if slug not in TOPICS:
            TOPICS[slug] = {"description": desc, "scenario": filename}


_build_registry()

# ── Derived dicts (back-compat) ──

SCRIPTS = {slug: (t["script"], t["description"]) for slug, t in TOPICS.items() if "script" in t}

SCENARIOS = {slug: (t["scenario"], t["description"]) for slug, t in TOPICS.items() if "scenario" in t}


# ── Script API ──


def load_script(name: str) -> str:
    if name not in SCRIPTS:
        available = ", ".join(SCRIPTS)
        raise KeyError(f"Unknown script: {name}. Available: {available}")
    filename, _ = SCRIPTS[name]
    path = _SCRIPTS / filename
    if not path.exists():
        raise FileNotFoundError(f"Script file not found: {path}")
    return path.read_text()


def list_scripts() -> list[tuple[str, str]]:
    return [(name, desc) for name, (_, desc) in SCRIPTS.items()]


# ── Scenario API ──


def load_scenario(name: str) -> Path:
    """Return the path to a scenario file."""
    if name not in SCENARIOS:
        available = ", ".join(SCENARIOS)
        raise KeyError(f"Unknown scenario: {name}. Available: {available}")
    filename, _ = SCENARIOS[name]
    path = _SCENARIOS / filename
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    return path


def list_scenarios() -> list[tuple[str, str]]:
    return [(name, desc) for name, (_, desc) in SCENARIOS.items()]


# ── Back-compat: SKILLS proxies SCRIPTS ──

SKILLS = SCRIPTS


def load_skill(name: str) -> str:
    return load_script(name)


def list_skills() -> list[tuple[str, str]]:
    return list_scripts()
