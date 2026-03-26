#!/bin/bash
pip install -e . -q 2>/dev/null
pkill -f 'pg-bench|bench_cli' 2>/dev/null
sleep 0.5
pg-bench serve parseltongue/core/validation/core.pltg >/dev/null 2>&1 &
pg-bench wait
pg-bench index . >/dev/null 2>&1 &
