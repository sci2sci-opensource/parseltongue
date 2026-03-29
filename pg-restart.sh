#!/bin/bash
pip install -e . -q 2>/dev/null
pkill -f 'pg-bench|bench_cli' 2>/dev/null
sleep 0.5
pg-bench serve parseltongue/core/validation/core.pltg --user "V" --assistant "Claude" >/dev/null 2>&1 &
pg-bench wait
pg-bench index . --ext py --ext pltg --ext md --ext txt --ext js --ext css --ext pgmd --ext html>/dev/null 2>&1 &
