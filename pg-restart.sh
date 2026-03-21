#!/bin/bash
pip install -e . -q 2>/dev/null
pkill -f 'pg-bench|bench_cli' 2>/dev/null
pg-bench serve parseltongue/core/validation/core.pltg &disown
#pg-bench serve parseltongue/core/demos/data_governance_pltg/checker.pltg --effects parseltongue.core.demos.data_governance_pltg.operators:GOVERNANCE_EFFECTS  &disown
pg-bench wait
pg-bench index . &disown

