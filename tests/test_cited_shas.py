"""The cited-SHA guard: a SHA written into a doc or a landing commit must resolve.

Why this exists: a docs commit cited a SHA that did not exist -- it was written from
memory rather than read from ``git log``. The document-control guard caught it, but only
by luck of position: the token happened to sit in the ``Last reconciled`` line, the one
place that guard checks. Anywhere else in any doc, or in a commit message, it would have
landed, and a citation that does not resolve makes the record unfalsifiable -- a reader
cannot tell a typo from an invention, and a claim like "merged at <sha>" cannot be
checked at all. The incident is recorded in ``7c2fdf9``.

What is checked:

* every hex token (7-40 characters) in **tracked markdown** -- the docs that will land;
* every hex token in the message of a commit **not yet on the base branch** (``main``,
  falling back to ``origin/main``) -- the commits about to land.

What is deliberately not checked: published history. It is never rewritten (rule 9) and
it legitimately cites dead SHAs, upstream pins and pre-republish commits; a whole-history
check could only stay green with a large allowlist that would have to include the
incident's own token. The docs half covers the whole current tree; the commits half
covers everything not already merged.

The allowlist below is the closed set of tokens that are cited on purpose and do not
resolve. A test asserts each is still cited in tracked markdown and still does not
resolve, so the list cannot rot into a place to park a real SHA.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[1]

#: SHA-shaped: 7-40 lowercase hex characters. Deliberately includes all-digit tokens --
#: ``20260924`` is the date in the ``rollback/pre-s1-20260924`` tag name, while
#: ``0200424`` and ``5908277`` are real commits -- so the guard cannot skip a class of
#: SHA citation to dodge a false positive.
_TOKEN_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

#: Tokens cited on purpose that cannot resolve in this repository, each with its reason.
#: "Cannot resolve" means unreachable from every ref: a commit object that lingers as a
#: dangling object in one clone is not a citation a reader can check out anywhere else,
#: so such a token stays allowlisted even when a local clone still holds it.
#: An entry is legal only while it is both cited in tracked markdown and unresolvable;
#: the honesty test below fails otherwise, so this cannot become a parking place for a
#: typo. The dead SHAs are documented in ``REMAINING_PLAN.md`` §2 and ``MARKETPLACE.md``.
ALLOWED_NON_RESOLVING: Dict[str, str] = {
    # Dead SHAs from the scrubbed pre-republish history. REMAINING_PLAN.md §2 and
    # docs/MARKETPLACE.md record them as "never push them anywhere public"; the docs
    # cite them only as the historical record of what must not be published.
    "e47e956": "dead SHA: pre-republish history (never push)",
    "0e5e39c": "dead SHA: pre-republish history (never push)",
    "93ef951": "dead SHA: pre-republish history (never push)",
    "6b62a21": "dead SHA: pre-republish history (never push)",
    "f15fe12": "dead SHA: pre-republish history (never push)",
    "9a2c1df": "dead SHA: pre-republish history (never push)",
    "437c89b": "dead SHA: the 2.8.0 catalog pin the republish made vanish",
    # Upstream, never in this repository: the fork branch the 2.8.0 catalog PR ended in.
    "cdfcd83": "upstream commit in NousResearch/hermes-agent, not this repo",
    # Commits the 2026-10-20 dependency round touched in sibling repositories. Each
    # was verified against its owning repo, but none of them is published: they live
    # only on local branches, so no reader can check them out yet. The reasons say so
    # rather than call them upstream commits, which would be untrue.
    # Not a SHA at all: the date in the `rollback/pre-s1-20260924` tag name.
    "20260924": "not a SHA: the date in the rollback/pre-s1-20260924 tag name",
    # GitHub Actions ids, not commits: the EM-407 hardening record cites the failing
    # 2026-10-15 3.13-leg job and its run so the flap stays checkable (NEXT_CHUNK Part A).
    "116561640133": "GitHub Actions job id, not a commit: the 2026-10-15 guard flap",
    # The chunk-48 landing's CI run (the figure of record's own run).
    "40654937822": "GitHub Actions run id, not a commit: the chunk-48 figures run",
    # The chunk-49 landing's CI run (the figure of record's own run).
    "40693532624": "GitHub Actions run id, not a commit: the chunk-49 figures run",
    # The chunk-50 landing's CI run (the figure of record's own run).
    "40721172839": "GitHub Actions run id, not a commit: the chunk-50 figures run",
    # The chunk-51 landing's CI run (the figure of record's own run).
    "40752588511": "GitHub Actions run id, not a commit: the chunk-51 figures run",
    "38775407380": "GitHub Actions run id, not a commit: the 2026-10-15 guard flap",
    # Same shape, same reason: EM-608's draft cites the 2026-10-18 warm-p95 flap's
    # job and run so the instance stays checkable (MASTER_TODO's flake record).
    "117631038052": "GitHub Actions job id, not a commit: the 2026-10-18 warm-p95 flap",
    "39112375641": "GitHub Actions run id, not a commit: the 2026-10-18 warm-p95 flap",
    "38861052493": "GitHub Actions run id, not a commit: the 2026-10-16 warm-p95 flap",
    # Same shape, same reason: the EM-603 5k-AC wall-clock flake. The EM-604
    # post-merge push re-ran `windows-import` on the same SHA and it read 440 ms
    # on a contended runner (CHANGELOG's Fixed entry); BASELINE.md cites the run
    # that then confirmed the commit green. All three stay checkable.
    "39216670780": "GitHub Actions run id, not a commit: the 2026-10-19 EM-603 5k-AC windows-import flap",
    "117942029064": "GitHub Actions job id, not a commit: the 2026-10-19 EM-603 5k-AC windows-import flap",
    "39219386624": "GitHub Actions run id, not a commit: the 2026-10-19 green run on 4cde953 (BASELINE.md)",
    "39226716232": "GitHub Actions run id, not a commit: the 2026-10-19 green run on adb1439, the EM-603 AC de-flake (BASELINE.md)",
    "39231027295": "GitHub Actions run id, not a commit: the 2026-10-19 post-merge re-run of the eleven on main at e6647e7, the EM-603 de-flake reconciliation (BASELINE.md)",
    "39236004212": "GitHub Actions run id, not a commit: the 2026-10-19 green run on 2fd7812, EM-605 slice 1 (BASELINE.md)",
    "39237280578": "GitHub Actions run id, not a commit: the 2026-10-19 post-merge re-run of the eleven on main at 2fd7812 (BASELINE.md)",
    # The EM-605/EM-606 landing: CI's first run on the branch (12/13 green, the
    # sole red the pre-existing identity-guard defect) and main's red guard run
    # it was compared against. Neither is a commit; both stay checkable.
    "39612171910": "GitHub Actions run id, not a commit: the 2026-10-21 EM-605/EM-606 landing branch run",
    "39629454711": "GitHub Actions run id, not a commit: the 2026-10-21 green run on 73bed69, the EM-605/EM-606 landing on main (BASELINE.md)",
    "39640594895": "GitHub Actions run id, not a commit: the 2026-10-21 green run on 06c39fd, the cited-SHA reachability fix landing (MASTER_TODO.md, BASELINE.md, CHANGELOG.md)",
    "39620615391": "GitHub Actions run id, not a commit: the 2026-10-21 EM-605/EM-606 landing run whose 3.12 log the figures were read from",
    # EM-607's landing run: green on its 13 check-runs, and the 3.12 job log the
    # figures of record are read from (BASELINE.md, MASTER_TODO.md, CHANGELOG.md).
    "39666424863": "GitHub Actions run id, not a commit: the 2026-10-21 EM-607 landing branch run on e0f39a5",
    # The EM-607 build commit's own run: red on one job, the figures guard's
    # ancestry assertion, which the docs record as the expected shape of a
    # commit that touches tests/ before the record is re-stamped. Cited as the
    # red half of that pair, never as a green figure.
    "39661990213": "GitHub Actions run id, not a commit: the 2026-10-21 EM-607 build-commit run, red on the figures ancestry assertion alone",
    # The S7 pair's build tip: red on the figures-guard pair alone (the record
    # then named the previous docs tip and the four new triples were not yet in
    # the record), cited in NEXT_CHUNK Part A as the third instance of the
    # documented pre-stamp shape.
    "39951235609": "GitHub Actions run id, not a commit: the 2026-10-23 EM-703/EM-705 build-tip run, red on the figures-guard pair alone (the expected pre-stamp shape)",
    "39465614611": "GitHub Actions run id, not a commit: main's red identity-guard run at a46adda (2026-10-21)",
    # The S7 pair's landing run on the record tip: green on its 13 check-runs,
    # and the 3.12 job log the figures of record are read from (BASELINE.md,
    # CHANGELOG.md, NEXT_CHUNK.md, MASTER_TODO.md).
    "39957746506": "GitHub Actions run id, not a commit: the 2026-10-23 EM-703/EM-705 landing run on 17684d9 whose 3.12 log the figures were read from",
    # The S8 packaging landing: green on its 13 check-runs (the pip-install smoke
    # step included), and the 3.12 job log the figures of record are read from
    # (BASELINE.md, CHANGELOG.md, NEXT_CHUNK.md, MASTER_TODO.md).
    "40521965355": "GitHub Actions run id, not a commit: the 2026-10-27 EM-806 landing run on ceb70cb whose 3.12 log the figures were read from",
    # The 2ff11c2 process slip (MASTER_TODO's deviations section): a docs-only
    # commit pushed to main before its CI ran. Cited so the post-push matrix's
    # green result stays checkable, and recorded as a slip rather than a policy.
    "40528252379": "GitHub Actions run id, not a commit: the 2026-10-27 post-push run on 2ff11c2 (docs-only slip, green 13/13)",
    "39251351180": "GitHub Actions run id, not a commit: the 2026-10-19 green run on 5258b46, chunk 43, the EM-605 slice-1 follow-up (BASELINE.md)",
    # Cited on purpose BECAUSE it does not resolve: BASELINE.md's "Citing CI
    # evidence" section uses it as the worked example of a run whose head_sha
    # names a rebased-away commit. Removing the citation breaks the lesson.
    "cb88d47": "unreachable on purpose: the rebased-away head_sha BASELINE.md uses as the worked example",
}

#: Sanity floors: the scan must keep seeing a real corpus, or a broken regex or glob
#: would pass vacuously. Actuals at landing: 30 markdown files, 107 tokens.
_MIN_FILES = 20
_MIN_TOKENS = 50


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text)


def _reachable_commits() -> Set[str]:
    """Every commit a reader of this repository could check out.

    Reachability from any ref plus HEAD, not object existence: a developer's clone can
    hold a dangling commit object the published repository never had (cb88d47 is the
    worked example in docs/plan/BASELINE.md), and a citation nobody can check out is a
    broken citation no matter whose clone the scan runs in.
    """
    if _git("rev-parse", "--is-shallow-repository").strip() == "true":
        raise AssertionError(
            "this clone is shallow, so the cited-SHA guard cannot see the history it "
            "has to check; fetch it first: git fetch --unshallow --tags --all"
        )
    out = _git("rev-list", "--all", "HEAD")
    return set(out.split())


def _peel_to_commits(tokens: List[str]) -> Dict[str, Optional[str]]:
    """Each token peeled to the full SHA of the commit it names, or None.

    The peel ``^{commit}`` is what is asked for, so a blob or tree hash is not a
    citation of a commit, and an annotated tag peels to the commit it points at.
    ``--batch-check`` answers in input order, so the mapping back is positional, and
    for a resolving abbreviation it prints the full object name, not the input token.
    """
    result = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=REPO,
        input="\n".join(f"{token}^{{commit}}" for token in tokens) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git cat-file failed: {result.stderr.strip()}"
    lines = result.stdout.splitlines()
    assert len(lines) == len(tokens), "batch-check did not answer every token"
    peeled: Dict[str, Optional[str]] = {}
    for token, line in zip(tokens, lines):
        parts = line.split()
        peeled[token] = parts[0] if len(parts) >= 2 and parts[1] == "commit" else None
    return peeled


def _resolved(tokens: Iterable[str]) -> Dict[str, bool]:
    """Which tokens name a commit in this repository's history.

    Two questions, and a citation has to pass both. It must peel to a commit, so a
    blob or tree hash is not a commit citation and an annotated tag counts as a
    citation of the commit it points at. And that commit must be reachable from a
    ref, because a citation nobody can check out is broken: a developer's clone can
    hold a dangling commit object the published repository never had (cb88d47 is the
    worked example in docs/plan/BASELINE.md).
    """
    ordered = sorted(set(tokens))
    if not ordered:
        return {}
    peeled = _peel_to_commits(ordered)
    reachable = _reachable_commits()
    return {
        token: sha is not None and sha in reachable
        for token, sha in peeled.items()
    }


def _tracked_markdown() -> List[Path]:
    return [REPO / rel for rel in _git("ls-files", "*.md").splitlines() if rel.strip()]


def _doc_citations() -> Dict[str, List[str]]:
    """token -> ``["file:line", ...]`` over every tracked markdown file."""
    citations: Dict[str, List[str]] = {}
    for path in _tracked_markdown():
        text = path.read_text(encoding="utf-8")
        for match in _TOKEN_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            citations.setdefault(match.group(), []).append(
                f"{path.relative_to(REPO).as_posix()}:{line}"
            )
    return citations


def _base_ref() -> str:
    """The branch a landing commit is measured against. Fails closed, like the
    identity guard: a range git cannot resolve is an error, never a pass.

    ``origin/main`` first, not the local ``main``: a local main can be stale, and a
    stale base makes already-landed commits look like they are about to land, so
    their messages get scanned and their citations flagged for no reason.
    """
    for ref in ("origin/main", "main"):
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=REPO,
            capture_output=True,
        )
        if probe.returncode == 0:
            return ref
    raise AssertionError(
        "cannot resolve a base branch (main or origin/main); the cited-SHA guard "
        "cannot tell which commits are about to land, so it fails closed"
    )


def _landing_commit_messages() -> List[Tuple[str, str]]:
    base = _base_ref()
    shas = [sha for sha in _git("rev-list", f"{base}..HEAD").split() if sha]
    return [(sha, _git("log", "-1", "--format=%B", sha)) for sha in shas]


def test_every_sha_cited_in_tracked_docs_resolves():
    citations = _doc_citations()
    resolved = _resolved(citations)
    unresolved = sorted(
        f"{token} ({citations[token][0]})"
        for token, ok in resolved.items()
        if not ok and token not in ALLOWED_NON_RESOLVING
    )
    assert not unresolved, (
        "SHA-like tokens in tracked docs that do not resolve to a commit (fix the "
        "citation, or add a documented reason to ALLOWED_NON_RESOLVING):\n  "
        + "\n  ".join(unresolved)
    )


def test_every_sha_cited_in_commits_about_to_land_resolves():
    per_token: Dict[str, List[str]] = {}
    for sha, message in _landing_commit_messages():
        for token in set(_tokens(message)):
            per_token.setdefault(token, []).append(sha[:8])
    resolved = _resolved(per_token)
    offenders = sorted(
        f"{token} (cited in {', '.join(sorted(per_token[token]))})"
        for token, ok in resolved.items()
        if not ok and token not in ALLOWED_NON_RESOLVING
    )
    assert not offenders, (
        "commit messages about to land cite SHAs that do not resolve to a commit:\n  "
        + "\n  ".join(offenders)
    )


def test_the_allowlist_entries_are_still_cited_and_still_do_not_resolve():
    citations = _doc_citations()
    resolved = _resolved(ALLOWED_NON_RESOLVING)
    for token, reason in ALLOWED_NON_RESOLVING.items():
        assert reason.strip(), f"{token} is allowlisted without a reason"
        assert token in citations, (
            f"{token} is allowlisted but no longer cited in tracked markdown; remove "
            "it from ALLOWED_NON_RESOLVING"
        )
        assert not resolved[token], (
            f"{token} now resolves to a commit; it no longer needs to be an exception"
        )


def test_the_docs_scan_is_not_silently_empty():
    files = _tracked_markdown()
    citations = _doc_citations()
    assert len(files) >= _MIN_FILES, f"only {len(files)} tracked markdown files found"
    assert len(citations) >= _MIN_TOKENS, f"only {len(citations)} SHA-like tokens found"


def test_a_blob_hash_is_not_a_commit_citation():
    """`^{commit}` is the question asked, so a content hash that happens to be in the
    object database is not a resolved citation."""
    blob = _git("rev-parse", "HEAD:AGENTS.md").strip()
    assert re.fullmatch(r"[0-9a-f]{40}", blob), "expected a full object name"
    assert _resolved([blob])[blob] is False


def test_the_token_rule_matches_sha_shapes_and_ignores_everything_else():
    text = (
        "resolves 1e40968 and 0200424; short 123456; long "
        + "a" * 41
        + "; non-hex 1e4096g; uppercase 1E40968"
    )
    assert _tokens(text) == ["1e40968", "0200424"]
