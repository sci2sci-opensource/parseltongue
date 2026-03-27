"""The Construct — skill loading for LLM agents.

"I know kung fu." — Neo
"""

from pathlib import Path

_CONSTRUCT = Path(__file__).parent

SKILLS = {
    "kung-fu": ("PG-SKILL_KUNG-FU.md", "Bench mastery — inspection, search, lens, diagnosis"),
    "to-connect": (
        "PGMD-SKILL_TO-CONNECT.md",
        "pgmd notebooks — prose is the illusion, you choose to see it with truth wired through",
    ),
    # "dodge-bullets":     ("DODGE-BULLETS.md",       "TODO: screening, diagnostics, consistency"),
    # "jump-program":      ("JUMP-PROGRAM.md",       "TODO: resolving dynamic refs, building consistent graphs, jumps within the system"),
    # "no-spoon-bending":  ("NO-SPOON-BENDING.md",   "TODO: effects, verify_manual, bending accepted terms"),
    # "read-the-code":     ("READ-THE-CODE.md",       "TODO: grounding layer, translating documents/data to facts and axioms"),
    # "about-matrix":      ("ABOUT-MATRIX.md",      "TODO: systems, composition, fundamental lang"),
    #
    # "the-truth":         ("THE-TRUTH.md",           "TODO: epistemics, std lib, grounding module, diffs"),
    #
    # "to-exit":           ("TO-EXIT.md",             "TODO: scoping, projection, delegates"),
    #
    # "to-fly":            ("TO-FLY.md",              "TODO: graph navigation, search, cross-navigation"),
    #
    #
}


def load_skill(name: str) -> str:
    if name not in SKILLS:
        available = ", ".join(SKILLS)
        raise KeyError(f"Unknown skill: {name}. Available: {available}")
    filename, _ = SKILLS[name]
    path = _CONSTRUCT / filename
    if not path.exists():
        raise FileNotFoundError(f"Skill file not found: {path}")
    return path.read_text()


def list_skills() -> list[tuple[str, str]]:
    return [(name, desc) for name, (_, desc) in SKILLS.items()]
