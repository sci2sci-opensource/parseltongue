B# Data Governance Demo — Cross-Layer Consistency

A biopharma company maintains three independent layers of data governance:

| Layer | Format | Contains |
|-------|--------|----------|
| **Technical catalog** | CSV | What actually exists in the data platform — paths, tables, cadences, owners |
| **Contracts** | Markdown | Legal agreements with external data providers — SLAs, retention, classification |
| **Business catalog** | Markdown | Business-facing data product descriptions — sources, refresh, classification |

Each layer is authored and maintained independently. Over time, drift accumulates: paths change, contracts expire, business entries reference datasets that no longer exist, refresh frequencies diverge.

## What Parseltongue does

The checker (`checker.pltg`) loads all three layers as documents, discovers entities at runtime via effects (`csv-rows`, `regex-match`, `list-tree-paths`, `doc-text`), and runs 9 cross-layer compliance checks — entirely through axiom pattern matching and splat reductions:

1. **Contract coverage** — every external dataset must appear in at least one contract
2. **Expired contracts** — expired contracts revoke all permitted uses
3. **Phantom references** — business products must not reference non-existent datasets
4. **Classification propagation** — product classification must be at least as restrictive as its most restrictive source
5. **Omics classification** — genomic/proteomic/transcriptomic data must be classified restricted
6. **Technical cross-check** — CSV fields must match generated facts
7. **Contract cross-check** — contract status facts must match document extraction
8. **Business cross-check** — product classification facts must match document extraction
9. **Final policy** — all checks ANDed into a single `policy-consistent` theorem

The final `policy-check` diff compares the derived `policy-consistent` result against the expected `true`.

## The vital stain

The visualization uses a **vital stain** — a runtime execution trace that captures the actual dependency edges as Parseltongue evaluates the checker. This is not static analysis. Every node in the graph is a real evaluated fact, and every edge is a real resolution that happened during execution. The stain propagates through the provenance chain, showing exactly which upstream facts contributed to each compliance decision.

## Quick start

```bash
pip install -e .
```

### Run the shell script

```bash
cd parseltongue/core/demos/data_governance_pltg
./run_viz.sh
```

This will:
1. Generate a **clean** (consistent) data estate and open its provenance visualization
2. Wait for you to press Enter
3. Inject ~15-20% corruptions across all three layers and open the corrupted visualization
4. Compare the two side by side

### Run manually

```bash
# Generate consistent baseline
python generate.py --clean --consistent-only

# Start bench with effects
pg-bench serve checker.pltg --effects parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS &
pg-bench wait

# Generate visualization
pg-bench eval '(fmt "viz" (scope hologram (dissect (stain policy-check))))' > viz-results/clean.html
open viz-results/clean.html

# Now inject corruptions and regenerate
python generate.py --clean
# Restart bench (runtime data changed)
pg-bench stop
pg-bench serve checker.pltg --effects parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS &
pg-bench wait
pg-bench eval '(fmt "viz" (scope hologram (dissect (stain policy-check))))' > viz-results/corrupt.html
open viz-results/corrupt.html
```

## Files

| File | Role |
|------|------|
| `checker.pltg` | Hand-written. The compliance checker — imports manifest + policy rules, runs all 9 checks |
| `policy_rules.pltg` | Hand-written. Axioms for compliance predicates (`contract-ok`, `class-ok`, `sla-ok`, etc.) |
| `util.pltg` | Hand-written. Utility axioms (`concat`, `resolve-all`, `cons-prepend`) |
| `main.pltg` | Hand-written. Entry point that imports checker |
| `operators.py` | Hand-written. Python effects: `csv-rows`, `regex-match`, `list-tree-paths`, `doc-text`, `s` |
| `generate.py` | Hand-written. Synthetic data generator — consistent baseline + corruption injection |
| `demo.py` | Hand-written. Python-side consistency checker (alternative to the .pltg checker) |
| `resources/` | **Generated.** Governance policy/protocol docs (hand-written), catalogs and contracts (generated) |
| `src/` | **Generated.** .pltg fact modules extracted from resources by `generate.py` |
| `manifest.json` | **Generated.** Log of every injected corruption |

## What corruptions look like

The generator (`generate.py`) injects ~15-20% corruptions:

- **Path drift** — business catalog says `s3://old-path`, technical catalog says `s3://new-path`
- **Table rename** — business references old table name, tech catalog has the new one
- **Phantom references** — business product references a dataset ID that doesn't exist in tech catalog
- **Contract expiry** — contract status flipped to "expired"
- **Classification downgrade** — business product classification weakened below contract requirement
- **SLA mismatch** — contract SLA doesn't match technical refresh cadence
- **Owner drift** — product owner changed to someone from the wrong department

Every corruption is logged to `manifest.json` with the exact field, old value, and new value.
