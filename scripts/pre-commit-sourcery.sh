#!/usr/bin/env bash
# Sourcery pre-commit gate — blocks commits with unresolved Sourcery findings.
#
# Installed as .git/hooks/pre-commit (symlink). Reviews ONLY the staged diff,
# so pre-existing issues in untouched files never block unrelated commits.
#
# Install:  ln -sf ../../scripts/pre-commit-sourcery.sh .git/hooks/pre-commit
# Bypass (emergency only):  git commit --no-verify
set -euo pipefail

# Locate the sourcery CLI (uv tool installs to ~/.local/bin)
SOURCERY=""
if command -v sourcery >/dev/null 2>&1; then
  SOURCERY="$(command -v sourcery)"
elif [ -x "$HOME/.local/bin/sourcery" ]; then
  SOURCERY="$HOME/.local/bin/sourcery"
fi

if [ -z "$SOURCERY" ]; then
  echo "sourcery-gate: Sourcery CLI not found. Install: uv tool install sourcery" >&2
  exit 1
fi

# Only run when Python files are staged for this commit
STAGED_PY="$(git diff --cached --name-only --diff-filter=ACM -- '*.py')"
if [ -z "$STAGED_PY" ]; then
  exit 0
fi

echo "sourcery-gate: reviewing staged Python changes..."

# Diff scoped to *.py so Sourcery reviews exactly what the gate guards;
# non-Python staged files don't leak into the review scope.
if ! "$SOURCERY" review --check --diff "git diff --cached -- '*.py'" --no-summary .; then
  echo "" >&2
  echo "sourcery-gate: review FAILED — fix the issues above, then re-stage (git add) and commit again." >&2
  echo "sourcery-gate: auto-fix hint: sourcery review --fix --diff \"git diff HEAD\"" >&2
  exit 1
fi

echo "sourcery-gate: clean."
exit 0
