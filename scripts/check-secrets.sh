#!/usr/bin/env bash
set -euo pipefail

patterns=(
  'BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY'
  'Bearer[[:space:]]+[A-Za-z0-9._~+/-]{24,}'
)
failed=0
for pattern in "${patterns[@]}"; do
  if grep -RInE --exclude-dir=.git --exclude-dir=build --exclude='*.lock' "$pattern" .; then
    failed=1
  fi
done
if [[ "$failed" -ne 0 ]]; then
  echo "Potential secret material found. Review matches before committing."
  exit 1
fi
echo "No obvious secret material found."
