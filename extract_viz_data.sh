#!/bin/sh
# Extract DATA, STRUCTURE_DATA, LAYERS, TAINT_DATA from a compiled viz HTML file.
# Usage: sh extract_viz_data.sh output.html
#   → creates output-data.js with just the JSON globals

set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <file1.html> [file2.html ...]" >&2
  exit 1
fi

for src in "$@"; do

base="$(basename "$src" .html)"
dir="$(dirname "$src")"
out="$dir/${base}-data.js"

python3 -c "
import re, sys

html = open(sys.argv[1]).read()

patterns = [
    ('DATA', r'const\s+DATA\s*=\s*(\[.*?\])\s*;'),
    ('STRUCTURE_DATA', r'const\s+STRUCTURE_DATA\s*=\s*(\[.*?\])\s*;'),
    ('LAYERS', r'const\s+LAYERS\s*=\s*(\{.*?\})\s*;'),
    ('TAINT_DATA', r'const\s+TAINT_DATA\s*=\s*(\{.*?\})\s*;'),
]

parts = []
for name, pat in patterns:
    m = re.search(pat, html, re.DOTALL)
    if m:
        parts.append(f'const {name} = {m.group(1)};')

if not parts:
    print('No data found', file=sys.stderr)
    sys.exit(1)

out = sys.argv[2]
with open(out, 'w') as f:
    f.write('\n\n'.join(parts) + '\n')

total = sum(len(p) for p in parts)
print(f'{out}  ({total:,} bytes total, {len(parts)} globals)')
for name, pat in patterns:
    m = re.search(pat, html, re.DOTALL)
    if m:
        print(f'  {name}: {len(m.group(1)):,} bytes')
" "$src" "$out"

done
