#!/bin/sh
# Check the bundled examples.
# Run from the repo root: sh examples/run-example.sh
# The check exits 1 because four example files fail on purpose —
# that is the expected result here.
set -e
cd "$(dirname "$0")/.."
echo "--- check all example files ---"
python3 src/frontmatter_checker.py --require title --require date --type tags:list examples/good.md examples/missing-date.md examples/empty-title.md examples/bad-tags.md examples/no-frontmatter.md || true
echo "--- check the good file alone ---"
python3 src/frontmatter_checker.py --require title --require date --type tags:list examples/good.md
