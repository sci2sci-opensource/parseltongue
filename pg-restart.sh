#!/bin/bash
pip install -e . -q 2>/dev/null
pkill -f bench_cli 2>/dev/null
sleep 0.5
pg-bench serve parseltongue/core/validation/core.pltg &disown
pg-bench wait
pg-bench index .
