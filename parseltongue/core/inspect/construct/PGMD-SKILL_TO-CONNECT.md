---
name: to-connect
description: Writing .pgmd notebooks — literate analysis where prose is the illusion and grounded data is the truth wired through it. Covers file format, pltg blocks, inline refs, rendering pipeline, and patterns.
---

# To Connect

> Prose is the illusion. You choose to see it — with truth wired through.

A `.pgmd` notebook interleaves markdown prose with `pltg` computation blocks. Every claim in the narrative connects back to grounded facts, derived metrics, or validated axioms. The rendered output shows both the story and the proof.

## Rendering

```bash
pg-bench render notebook.pgmd -o output.html        # render to file
pg-bench render notebook.pgmd                        # render to stdout
pg-bench render notebook.pgmd -t "Q3 Report"         # custom title
```

The renderer executes all pltg blocks, builds a bench (lens + diagnostics), and produces self-contained HTML with a notebook view, structure view, layers, and graph.

## File format

A `.pgmd` file is markdown. Code blocks with `scheme` language and a `;; pltg` comment on the first line are treated as executable pltg blocks. Everything else is prose.

```markdown
# Title

Prose paragraph with **markdown** formatting.

` ` `scheme
;; pltg Block Name
(fact revenue 5000000 :evidence (evidence "memo" :quotes ("Revenue: $5M") :explanation "TTM"))
(derive growth-rate (/ revenue baseline) :using (revenue baseline))
` ` `

Revenue is $[[fact:revenue]], growing at [[term:growth-rate]]x.
```

The `;; pltg` marker and block name are required. The name appears in the rendered output header.

## Inline references

References connect prose to computed values. They resolve at render time.

| Syntax | Renders as | Use |
|--------|-----------|-----|
| `[[fact:revenue]]` | The fact's value with footnote | Show a ground truth value |
| `[[term:growth-rate]]` | The derived value with footnote | Show a computed metric |
| `[[~term:margin-check]]` | Silent superscript footnote only | Validation badge — no inline value |
| `$[[fact:revenue]]` | `$` prefix before value | Dollar amounts |
| `[[fact:nrr]]%` | `%` suffix after value | Percentages |
| `[[term:ratio]]x` | `x` suffix after value | Multipliers |

Prefix/suffix characters stick to the resolved value. `$[[fact:revenue]]` renders as `$2.4M`, not `$ 2.4M`.

Silent refs (`~`) are for validation checks — they show a small superscript footnote number without displaying the value inline. Use them after the claim they validate: `Gross margin is healthy[[~term:margin-check]]`.

## Three patterns

### Standalone — everything in one file

All facts, computation, and prose in a single `.pgmd`. Self-contained, shareable.

```markdown
` ` `scheme
;; pltg Core Facts
(load-document "memo" "source/memo.txt")
(fact arr 2800000 :evidence (evidence "memo" :quotes ("ARR: $2,800,000") :explanation "Current ARR"))
(fact cogs 480000 :evidence (evidence "memo" :quotes ("COGS: $480,000") :explanation "TTM COGS"))
` ` `

` ` `scheme
;; pltg Metrics
(derive gross-margin (/ (- revenue cogs) revenue) :using (revenue cogs))
(axiom margin-ok (> ?m 0.6) :origin "gross margin > 60%")
(derive margin-check margin-ok :bind ((?m gross-margin)) :using (gross-margin margin-ok))
` ` `

Gross margin: **[[term:gross-margin]]%**[[~term:margin-check]].

` ` `scheme
;; pltg Review
(verify-manual (quote margin-ok) "Claude")
` ` `
```

In standalone, the review block lives at the end of the same file — no separate `review.pltg` needed. Only verify assumptions (`:origin`-based axioms), not grounded facts.

Best for: technical deep-dives, prototyping, self-contained reproducible analysis.

### Explicit — import facts, compute inline

Import a facts module, then derive metrics in the notebook's pltg blocks.

```markdown
` ` `scheme
;; pltg Load Facts
(import (quote ..facts.company_facts company))
` ` `

` ` `scheme
;; pltg Margin Analysis
(derive gross-margin (/ (- company.revenue company.cogs) company.revenue) :using (company.revenue company.cogs))
` ` `

Revenue: $[[fact:company.revenue]], margin: [[term:gross-margin]]%.
```

The `(import (quote ..module alias))` syntax gives a short name to the module. `company.revenue` resolves to the canonical `facts.company_facts.revenue`.

Best for: technical analyses where facts are maintained separately. Can connect to much larger pltg systems — the notebook is a view into an existing formal model.

### Implicit — import pre-computed analysis

Import both facts and a rules module that already derives everything. The notebook is pure narrative.

```markdown
` ` `scheme
;; pltg Load Analysis
(import (quote ..facts.company_facts))
(import (quote ..analysis.company_rules))
` ` `

LTV/CAC of [[term:company_rules.ltv-to-cac]]x[[~term:company_rules.ltv-cac-check]] with [[fact:company_facts.nrr]]% NRR.
```

Best for: sharing with non-technical stakeholders. The notebook is clean, non-threatening prose — no visible computation, just narrative with grounded references. Analysts maintain the logic separately; writers author the story. Connects to the full pltg system — the notebook is a readable surface over arbitrarily complex formal models.

## Block execution

Each pltg block executes in order. Later blocks can reference names defined in earlier blocks. A block that errors shows the error in the rendered output — remaining blocks continue executing.

The last non-directive expression in a block becomes the block's return value, displayed in the "Out:" row:

```scheme
;; pltg Quick Check
(derive ratio (/ revenue cost) :using (revenue cost))
ratio
```

`(print "message")` produces stdout, shown in green. Errors show in red.

## Validation pattern

Axioms define business rules with `?`-variable placeholders. Derives bind concrete values and check them:

```scheme
;; pltg Checks
(axiom healthy-margin (> ?m 0.6) :origin "gross margin must exceed 60%")
(derive margin-check healthy-margin :bind ((?m gross-margin)) :using (gross-margin healthy-margin))
```

If `gross-margin` > 0.6, the derive succeeds (theorem is true). Reference it silently in prose:

```markdown
Margin is strong[[~term:margin-check]].
```

The rendered output shows a superscript footnote linking to the validation result. Margin pills in the right gutter show all referenced nodes for each paragraph.

## Module layout

For explicit/implicit patterns, organize as:

```
project/
  source/
    memo.txt              # ground truth document
  facts/
    company_facts.pltg    # facts extracted from source
  analysis/
    company_rules.pltg    # derives, axioms, validations
  notebooks/
    report.pgmd           # the notebook
    review-report.pltg    # post-session verification (created after)
```

Import with relative dots: `..facts.company_facts` means "up one directory, into facts/, load company_facts.pltg".

## Value formatting

The renderer auto-formats numeric values:

- >= 1,000,000 → `2.4M`
- >= 1,000 → `18,200`
- 0 < x < 1 → `80.00%` (percentage)
- Integer → no decimals
- Boolean → `true` / `false`

Prefix/suffix from the ref syntax is prepended/appended: `$2.4M`, `80.00%%`, `4.91x`.

## Verification protocol

`verify-manual` is **not** part of the analysis itself. It's a post-hoc review step — used after the main work is done, or when assumptions were made outside of documented evidence.

### When to use

- **After the main analysis session is complete** — never during authoring
- When assumptions were made outside documented evidence (`:origin`-based facts)

### Where verification lives

**Standalone**: inline block at the end of the `.pgmd` — no separate file needed:

```scheme
;; pltg Review
(verify-manual (quote margin-ok) "Claude")
```

**Explicit/Implicit**: separate `review-{notebook}.pltg` next to the `.pgmd`, imported after everything else:

```
project/
  notebooks/
    report.pgmd
    review-report.pltg        # created AFTER main session
```

```scheme
;; review-report.pltg — post-session verification
;; Session: Alice + Claude, 2026-03-26

(import (quote ..analysis.company_rules))

;; Assistant-signed (assumptions made during analysis)
(verify-manual (quote company_rules.market-threshold) "Claude")
(verify-manual (quote company_rules.growth-assumption) "Claude")

;; User-signed (explicitly requested by user)
(verify-manual (quote company_facts.adj-revenue) "Alice")
```

The review file imports the modules it needs to verify, then references names with `(quote ...)`. It's imported in the `.pgmd` after the analysis imports.

### Signature rules

1. **Never use the user's name** unless they explicitly request it
2. **Default to assistant name** from the bench session, or `"system"` if anonymous
3. **Always inform the user** about items that need review: "These N items are assumptions outside the source documents: ..."
4. **Ask before signing**: "Should I verify these under my name (Claude), or would you like to approve them under yours?"
5. **User-initiated**: only when the user says "verify under my name" or "I confirm this"

### Workflow

1. Build the analysis (facts, axioms, derives, diffs) — no verify-manual anywhere
2. Screen: `pg screen --what issues`
3. Identify `:origin`-based items — these are ungrounded assumptions
4. Present them to the user
5. Create `review.pltg` with the agreed signatures
6. Import it in `main.pltg` and reload

The logbook (`.parseltongue-bench/logbook.jsonl`) records who booked the bench session, so signatures trace back to a real session entry.

## Working example

Study the AI2AI demo at `parseltongue/core/demos/ai2ai_pgmd/`. It contains all three patterns side by side:

```
parseltongue/core/demos/ai2ai_pgmd/
  source/
    series_a_memo.txt         # ground truth — the investment memo
  facts/
    ai2ai_facts.pltg          # 30+ facts extracted with evidence
  analysis/
    ai2ai_rules.pltg          # derives, axioms, validation checks
  notebooks/
    standalone.pgmd            # standalone pattern — everything in one file
    explicit.pgmd              # explicit pattern — imports facts, computes inline
    implicit.pgmd              # implicit pattern — imports pre-computed analysis, pure narrative
  render_all.py                # renders all three to pgmd_out/
```

Render them with:

```bash
pg-bench render parseltongue/core/demos/ai2ai_pgmd/notebooks/implicit.pgmd -o temp/implicit.html
```
