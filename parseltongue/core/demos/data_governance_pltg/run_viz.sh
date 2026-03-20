#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

EFFECTS="parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS"
EVAL_CMD='(fmt "viz" (scope hologram (dissect (stain policy-check))))'

mkdir -p viz-results

cleanup() {
  pkill -f 'pg-bench|bench_cli' 2>/dev/null || true
}
trap cleanup EXIT

start_bench() {
  pkill -f 'pg-bench|bench_cli' 2>/dev/null || true
  sleep 1
  rm -rf .parseltongue-bench/
  pg-bench serve checker.pltg --effects "$EFFECTS" &disown 2>/dev/null
  pg-bench wait 2>/dev/null
}

# ── Phase 1: Clean data estate ──
echo "=== Phase 1: Generating consistent data estate ==="
python generate.py --clean --consistent-only

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
python generate.py --clean

echo "Restarting bench with corrupted data..."
start_bench

echo "Generating corrupted visualization..."
pg-bench eval "$EVAL_CMD" > viz-results/corrupt.html 2>/dev/null
open viz-results/corrupt.html
echo "Opened viz-results/corrupt.html"

echo ""
echo "=== Done ==="
echo "Clean:    viz-results/clean.html"
echo "Corrupt:  viz-results/corrupt.html"
