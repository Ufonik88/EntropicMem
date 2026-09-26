#!/usr/bin/env bash
# CI identity guard: every commit that lands must be authored/committed by a
# noreply address.
#
# Why this exists: GitHub web merges take the merge commit's author from the
# merging ACCOUNT's email, not from the repo's git config. On 2026-09-26 that put
# a personal work email into five public merge commits on main, and repairing it
# required rewriting published history (see ENTROPICMEM_PRIVACY_REPAIR.md). The
# push-to-main trigger is the alarm for exactly that case, because a web merge
# only becomes a commit after CI has already run on the PR.
#
# Usage:
#   check_commit_identity.sh <rev-range>    e.g. "abc..def" (a PR) or "HEAD" (whole history)
#
# Fails closed: a range git cannot resolve is an error (exit 2), never a pass.
#
# Allowed (and only these):
#   * <anything>@users.noreply.github.com   GitHub's per-account noreply
#   * noreply@github.com                    GitHub web-flow / merge commits
#   * noreply@anthropic.com                 bot/agent commits
set -euo pipefail

RANGE="${1:?usage: check_commit_identity.sh <range>}"

if ! ALL=$(git rev-list "$RANGE" 2>&1); then
  echo "identity-guard: ERROR: cannot resolve '$RANGE': $ALL" >&2
  exit 2
fi

if [ -z "$ALL" ]; then
  echo "identity-guard: no commits in range '$RANGE', nothing to check."
  exit 0
fi

ALLOWED_RE='(@users\.noreply\.github\.com$|^noreply@github\.com$|^noreply@anthropic\.com$)'
BAD=$(printf '%s\n' "$ALL" | xargs -r git log --no-walk --format='%H%x09%ae%x09%ce%x09%s' \
      | awk -F'\t' -v re="$ALLOWED_RE" '$2 !~ re || $3 !~ re {print}')

COUNT=$(printf '%s\n' "$ALL" | wc -l | tr -d ' ')
if [ -n "$BAD" ]; then
  echo "identity-guard: FAILED. Non-noreply identity in '$RANGE':" >&2
  echo >&2
  printf '%s\n' "$BAD" | while IFS=$'\t' read -r sha ae ce subj; do
    printf '  %s\n    author:    %s\n    committer: %s\n    subject:   %s\n' \
      "$sha" "$ae" "$ce" "$subj" >&2
  done
  echo >&2
  echo "Fix: set 'git config user.email Ufonik88@users.noreply.github.com' and" >&2
  echo "amend, or use 'gh pr merge --merge' from an account whose primary email" >&2
  echo "is the noreply address." >&2
  exit 1
fi

echo "identity-guard: OK. $COUNT commit(s) in '$RANGE', all noreply."
