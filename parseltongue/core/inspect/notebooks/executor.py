"""Execute a .pgmd notebook through the bench pipeline.

CompanionTracker runs pltg blocks → companion .pltg file.
Bench.prepare(companion) → full pipeline with probe, structure, diagnostics.
Each block is then re-interpreted to capture return values.
"""

from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parseltongue.core.atoms import SILENCE
from parseltongue.core.inspect.bench import Bench
from parseltongue.core.notebooks.companion import CompanionTracker, companion_path_for
from parseltongue.core.notebooks.pgmd import PgmdBlock, parse_pgmd


@dataclass
class BlockOutput:
    """Output from executing a single pltg block."""

    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    result: Any = None  # return value from interpret (last non-directive expression)


@dataclass
class NotebookResult:
    """Result of executing a .pgmd notebook through bench."""

    blocks: list[PgmdBlock]
    block_outputs: dict[int, BlockOutput]
    bench: Bench | None
    comp_path: Path | None = None
    error: str | None = None


def execute_pgmd(pgmd_path: str | Path) -> NotebookResult:
    """Execute a .pgmd file and return bench + execution artifacts.

    Pipeline:
    1. Parse pgmd → blocks (prose + pltg + code)
    2. CompanionTracker executes pltg blocks → companion .pltg
    3. Bench.prepare(companion) → loaded with full probe
    4. Re-interpret each block to capture return values
    """
    pgmd_path = Path(pgmd_path).resolve()
    source = pgmd_path.read_text()
    blocks = parse_pgmd(source)
    pltg_blocks = [(i, b) for i, b in enumerate(blocks) if b.kind == "pltg"]

    if not pltg_blocks:
        return NotebookResult(blocks=blocks, block_outputs={}, bench=None)

    # Step 1: Build companion file via tracker
    comp_path = companion_path_for(pgmd_path)
    if comp_path.exists():
        comp_path.unlink()

    tracker = CompanionTracker(pgmd_path, comp_path)
    block_outputs: dict[int, BlockOutput] = {}

    for pltg_num, (block_idx, block) in enumerate(pltg_blocks):
        old_out, old_err = sys.stdout, sys.stderr
        cap_out, cap_err = io.StringIO(), io.StringIO()
        sys.stdout = cap_out
        sys.stderr = cap_err
        error = None
        try:
            tracker.execute(pltg_num, block.content)
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

        block_outputs[pltg_num] = BlockOutput(
            stdout=cap_out.getvalue(),
            stderr=cap_err.getvalue(),
            error=error,
        )

    # Step 2: Load through bench for full probe
    bench = Bench()
    bench.purge()
    try:
        bench.prepare(str(comp_path))
    except Exception:
        return NotebookResult(
            blocks=blocks,
            block_outputs=block_outputs,
            bench=None,
            comp_path=comp_path,
            error=traceback.format_exc(),
        )

    # Step 3: Re-interpret each block to capture stdout, stderr, return values
    try:
        result_obj = bench.result(str(comp_path))
        if result_obj and result_obj.system:
            system = result_obj.system.copy(name="nb-eval", overridable=True)
            for pltg_num, (block_idx, block) in enumerate(pltg_blocks):
                bo = block_outputs[pltg_num]
                old_out, old_err = sys.stdout, sys.stderr
                cap_out, cap_err = io.StringIO(), io.StringIO()
                sys.stdout = cap_out
                sys.stderr = cap_err
                try:
                    _, val = system.interpret(block.content)
                    if val is not SILENCE and val is not None:
                        bo.result = val
                except Exception:
                    if not bo.error:
                        bo.error = traceback.format_exc()
                finally:
                    sys.stdout = old_out
                    sys.stderr = old_err
                    captured_out = cap_out.getvalue()
                    captured_err = cap_err.getvalue()
                    if captured_out:
                        bo.stdout = (bo.stdout + "\n" + captured_out).strip() if bo.stdout else captured_out
                    if captured_err:
                        bo.stderr = (bo.stderr + "\n" + captured_err).strip() if bo.stderr else captured_err
    except Exception:
        pass  # non-fatal — we still have the bench

    return NotebookResult(
        blocks=blocks,
        block_outputs=block_outputs,
        bench=bench,
        comp_path=comp_path,
    )
