#!/bin/bash
# Usage: sh render.sh path/to/file.pgmd [title]
# Renders to temp/ and opens in browser.

set -e

file="$1"
title="${2:-}"

if [ -z "$file" ]; then
  echo "Usage: sh render.sh <file.pgmd> [title]" >&2
  exit 1
fi

name=$(basename "$file" | sed 's/\.pg\.md$//; s/\.pgmd$//')
out="temp/${name}.html"
mkdir -p temp

if [ -n "$title" ]; then
  pg-bench render "$file" -t "$title" -o "$out" --user "V" --assistant "Opus"
else
  pg-bench render "$file" -o "$out" --user "V" --assistant "Opus"
fi

#open "$out"
