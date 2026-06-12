#!/usr/bin/env bash
# Generate or verify checksums of guardrail files. Verified in CI; any drift fails.
set -euo pipefail
cd "$(dirname "$0")/.."

MANIFEST=".claude/hooks/manifest.sha256"
FILES=(
  ".claude/settings.json"
  ".claude/hooks/pre_tool_guard.py"
  "scripts/guardrails.sh"
  ".github/workflows/guardrails.yml"
  "CODEOWNERS"
)
# include every IAM policy file present
while IFS= read -r f; do FILES+=("$f"); done < <(find iam -type f -name '*.json' 2>/dev/null | sort)

sha() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }

case "${1:-verify}" in
  generate)
    sha "${FILES[@]}" > "$MANIFEST"
    echo "manifest written: $MANIFEST" ;;
  verify)
    [ -f "$MANIFEST" ] || { echo "missing $MANIFEST — run: scripts/guardrails.sh generate (human only)"; exit 1; }
    sha --check "$MANIFEST" ;;
  *) echo "usage: guardrails.sh [generate|verify]"; exit 1 ;;
esac
