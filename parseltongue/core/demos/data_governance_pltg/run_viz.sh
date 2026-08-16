#!/bin/bash
# Data Governance demo visualization.
#
# Requires lib_paths=[parseltongue/core/] for correct module
# qualification — pg-bench provides this via Bench.STD_PATH.
# Without it, sub-module facts lack the "src.manifest." prefix
# and (s ...) resolution fails.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

SCALE="${1:-1}"

EFFECTS="parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS"
EVAL_CMD='(fmt "viz" (scope hologram (dissect (stain policy-check))))'

mkdir -p viz-results

cleanup() {
  pkill -f 'pg-bench|bench_cli' 2>/dev/null || true
}
trap cleanup EXIT

start_bench() {
  local entry="${1:-checker.pltg}"
  pkill -f 'pg-bench|bench_cli' 2>/dev/null || true
  sleep 1
  rm -rf .parseltongue-bench/
  pg-bench serve "$entry" --effects "$EFFECTS" &disown 2>/dev/null
  pg-bench wait 2>/dev/null
}

# ── Phase 1: Clean data estate ──
echo "=== Phase 1: Generating consistent data estate (scale=$SCALE) ==="
python generate.py --clean --consistent-only --scale "$SCALE"

echo "Starting bench..."
start_bench

echo "Generating clean visualization..."
pg-bench eval "$EVAL_CMD" > viz-results/clean.html 2>/dev/null
open viz-results/clean.html
echo "Opened viz-results/clean.html"

echo ""
echo "=== Press Enter to inject corruptions ==="
read -r

# ── Phase 2: Corrupted data estate ──
echo "=== Phase 2: Injecting corruptions ==="
python generate.py --clean --scale "$SCALE"

echo "Restarting bench with corrupted data..."
start_bench

echo "Generating corrupted visualization..."
pg-bench eval "$EVAL_CMD" > viz-results/corrupt.html 2>/dev/null
open viz-results/corrupt.html
echo "Opened viz-results/corrupt.html"

echo ""
echo "=== Press Enter for the regulator to arrive (Amendment 2025-A) ==="
read -r

# ── Phase 3: Same estate, amended policy — the graph reshapes ──
echo "=== Phase 3: Re-judging the estate under Amendment 2025-A ==="

# The checker builds fact names textually, so it must stay the main
# module — the amendment joins it in one flat namespace by concatenation.
cat checker.pltg policy_amendment.pltg > checker_amended.pltg

echo "Restarting bench with the amended checker..."
start_bench checker_amended.pltg

echo "Generating amended visualization..."
EVAL_AMENDED='(fmt "viz" (scope hologram (dissect (stain policy-check-amended))))'
pg-bench eval "$EVAL_AMENDED" > viz-results/amended.html 2>/dev/null
open viz-results/amended.html
echo "Opened viz-results/amended.html"

echo ""
echo "=== Done ==="
echo "Clean:    viz-results/clean.html    (baseline — data fine, law lenient)"
echo "Corrupt:  viz-results/corrupt.html  (data moved — same shape, values bleed)"
echo "Amended:  viz-results/amended.html  (law moved on the same estate — the graph recalculates its shape)"
