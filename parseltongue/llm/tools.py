"""
Tool definitions for the three-pass LLM pipeline.

Each pass uses its own tool via tool_choice="required",
so the LLM must always call the tool — no prose leakage.
"""

# Pass 1: extract facts, axioms, and terms from documents
EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": "extract",
        "description": (
            "Extract facts, axioms, and terms from the source documents "
            "as parseltongue s-expression directives. "
            "Supported directives: fact, axiom, defterm. "
            "Each directive must include :evidence with verbatim quotes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_output": {
                    "type": "string",
                    "description": "Parseltongue fact/axiom/defterm directives",
                },
            },
            "required": ["dsl_output"],
        },
    },
}

# Pass 2: build derivations and diffs from the blinded system state
DERIVE_TOOL = {
    "type": "function",
    "function": {
        "name": "derive",
        "description": (
            "Build derivations and comparisons from the existing system state. "
            "Supported directives: derive, diff, defterm (for intermediates). "
            "Fact values are hidden — reason from structure only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_output": {
                    "type": "string",
                    "description": "Parseltongue derive/diff/defterm directives",
                },
            },
            "required": ["dsl_output"],
        },
    },
}

# Pass 3: fact-check — cross-validate with full DSL capabilities
FACTCHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "factcheck",
        "description": (
            "Cross-validate the system state by introducing alternative "
            "facts, axioms, computation paths, and registering diffs. "
            "Supported directives: fact, axiom, defterm, derive, diff. "
            "Every verification angle MUST end with a (diff ...) — "
            "diffs are how the system detects consistency issues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dsl_output": {
                    "type": "string",
                    "description": "Parseltongue directives for cross-validation",
                },
            },
            "required": ["dsl_output"],
        },
    },
}

# Pass 4: produce a grounded markdown answer with inline references
ANSWER_TOOL = {
    "type": "function",
    "function": {
        "name": "answer",
        "description": (
            "Produce the final answer as markdown with [[type:name]] "
            "inline references to parseltongue entities. "
            "Valid types: fact, term, axiom, theorem, quote, diff."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "Markdown answer with [[type:name]] reference tags",
                },
            },
            "required": ["markdown"],
        },
    },
}
