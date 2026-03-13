#!/bin/bash
pip install -e . -q 2>/dev/null
pkill -f 'pg-bench|bench_cli' 2>/dev/null
pg-bench serve parseltongue/core/validation/core.pltg &disown
pg-bench wait
pg-bench index . &
