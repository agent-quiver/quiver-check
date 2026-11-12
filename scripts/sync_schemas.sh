#!/usr/bin/env bash
# Copy the schemas from a pack-standard checkout at one commit, and record the commit and each file's sha256.
# The only way the schemas change: never edit src/quiver_check/schemas/ by hand. tests/test_schemas.py holds it.
# Usage: scripts/sync_schemas.sh <pack-standard checkout> <commit or tag>
set -euo pipefail
src=$1 ref=$2
dest=src/quiver_check/schemas
commit=$(git -C "$src" rev-parse "$ref^{commit}")
for f in pack.schema.json manifest.schema.json; do
  git -C "$src" show "$commit:schemas/$f" > "$dest/$f"
done
{
  echo "# Written by scripts/sync_schemas.sh; do not edit."
  echo "source: https://github.com/agent-quiver/pack-standard"
  echo "ref: $ref"
  echo "commit: $commit"
  echo "sha256:"
  for f in pack.schema.json manifest.schema.json; do
    echo "  $f: $(sha256sum "$dest/$f" | cut -d' ' -f1)"
  done
} > "$dest/SOURCE.yaml"
echo "schemas from pack-standard $ref ($commit)"
