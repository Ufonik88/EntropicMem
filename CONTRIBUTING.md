# Contributing to EntropicMem

Thanks for considering a contribution! This project is **public-facing** —
everything you commit, including git history, is visible to anyone.

## The One Rule: No Personal Data

Never commit anything that identifies a real person or private system:

- ❌ Real names (owner, family, friends, colleagues)
- ❌ Home paths like `/home/username/...`
- ❌ Emails, phone numbers, addresses, account numbers, IPs
- ❌ Employer/client names or private projects
- ❌ Credentials, tokens, `.env`, database dumps, memory/vault/graph exports

Use neutral placeholders instead: `Alice`, `Bob`, `Acme Corp`, `~`, `$HOME`.

## Before You Commit

```bash
git add <files>
git diff --cached          # read your own diff
git status                 # check for stray files
```

Ask yourself: *"Would I be comfortable with a stranger reading this in ten
years?"* If the answer is no, don't commit it.

## Generated Data

Exports of live memory (graph exports, database dumps, vault snapshots) must
**never** be committed. Keep them in `.gitignore`-covered local paths only.

## History Scrubbing

If personal data slips into history, the fix is `git filter-repo` (delete the
affected paths from all commits, replace personal strings, force-push) — a
forward-only fix is not enough.

## Review

All PRs are reviewed. Expect questions about anything that looks personal —
it's not you, it's the public repo.
