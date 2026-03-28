"""The Construct — two modes, one place.

Scripts are for agents. Scenarios are for humans.

"I know kung fu." — Neo
"""

from pathlib import Path

_CONSTRUCT = Path(__file__).parent
_SCRIPTS = _CONSTRUCT / "scripts"
_SCENARIOS = _CONSTRUCT / "scenarios"

# ── Scripts: agent instructions (.md) ──

SCRIPTS = {
    "kung-fu": ("PG-SKILL_KUNG-FU.md", "Bench mastery — inspection, search, lens, diagnosis"),
    "to-connect": (
        "PGMD-SKILL_TO-CONNECT.md",
        "pgmd notebooks — prose is the illusion, you choose to see it with truth wired through",
    ),
    # "dodge-bullets":     ("DODGE-BULLETS.md",       "TODO: screening, diagnostics, consistency"),
    # "jump-program":      ("JUMP-PROGRAM.md",        "TODO: resolving dynamic refs, building consistent graphs, jumps within the system"),
    # "no-spoon-bending":  ("NO-SPOON-BENDING.md",    "TODO: effects, verify_manual, bending accepted terms"),
    # "read-the-code":     ("READ-THE-CODE.md",        "TODO: grounding layer, translating documents/data to facts and axioms"),
    # "about-matrix":      ("ABOUT-MATRIX.md",         "TODO: systems, composition, fundamental lang"),
    # "the-truth":         ("THE-TRUTH.md",             "TODO: epistemics, std lib, grounding module, diffs"),
    # "to-exit":           ("TO-EXIT.md",               "TODO: scoping, projection, delegates"),
    # "to-fly":            ("TO-FLY.md",                "TODO: graph navigation, search, cross-navigation"),
}

# ── Scenarios: human guides (.pgmd folders, renderable to HTML) ──

SCENARIOS = {
    "white-rabbit": (
        "INTRO_WHITE-RABBIT.pgmd",
        "Introduction — what parseltongue is and why it exists",
    ),
    # "kung-fu":     ("kung-fu/",     "Bench mastery — interactive walkthrough"),
    # "to-connect":  ("to-connect/",  "pgmd notebooks — building truth-wired prose"),
}


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
    """Return the path to a scenario's pgmd folder."""
    if name not in SCENARIOS:
        available = ", ".join(SCENARIOS)
        raise KeyError(f"Unknown scenario: {name}. Available: {available}")
    dirname, _ = SCENARIOS[name]
    path = _SCENARIOS / dirname
    if not path.exists():
        raise FileNotFoundError(f"Scenario folder not found: {path}")
    return path


def list_scenarios() -> list[tuple[str, str]]:
    return [(name, desc) for name, (_, desc) in SCENARIOS.items()]


# ── Back-compat: SKILLS proxies SCRIPTS ──

SKILLS = SCRIPTS


def load_skill(name: str) -> str:
    return load_script(name)


def list_skills() -> list[tuple[str, str]]:
    return list_scripts()
