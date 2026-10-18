"""EM-602, slice 1 — frontmatter and wikilink robustness (S6).

The vault is hand-editable Markdown, so two properties have to hold or the
vault silently corrupts itself:

* **The frontmatter block round-trips.** The old writer built lines with
  f-strings (`title: "{title}"`), so a title containing `"`, a backslash or a
  newline produced a block that read back differently — or did not parse at
  all — while the note claimed to be saved. The new writer quotes and escapes,
  and falls back to a block scalar for anything multi-line.
* **A `---` in the body is not a delimiter.** The old reader split the whole
  file on `---` (`text.split("---", 2)`), so a horizontal rule or a code fence
  in the body truncated the note.

It also pins the wikilink grammar (target, `|alias`, `#heading`, `^block`,
`!embed`) that the graph edges are built from, and the fact that the v2
`em_internal.vault` module is now a thin shim over `em.vault.frontmatter` (one
implementation, so a fix cannot land in only one of them).

Slice 2 — `note_id` as the full vault-relative path and the `index.db`
`user_version` 2 migration — is recorded and not built here.

Rules: invented data only.
"""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "plugins" / "entropicmem" / "scripts"
for entry in (str(REPO), str(SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from em.vault.frontmatter import (  # noqa: E402
    DELIMITER,
    Wikilink,
    dump_frontmatter,
    dump_scalar,
    load_frontmatter,
    parse_wikilinks,
    split_frontmatter,
)
from em_internal.vault import Note, Vault  # noqa: E402

needs_yaml = pytest.mark.skipif(
    importlib.util.find_spec("yaml") is None, reason="PyYAML not installed"
)


# --- the delimiter rule ------------------------------------------------------


def test_a_delimiter_only_counts_at_the_file_start():
    text = '---\ntitle: "T"\n---\nbody\n---\nmore\n---\n'
    block, body = split_frontmatter(text)
    assert block == 'title: "T"\n'
    assert body == "body\n---\nmore\n---\n"


def test_an_indented_or_extended_marker_is_not_a_delimiter():
    for start in (" ---\n", "----\n", "--- \n", "\t---\n"):
        block, body = split_frontmatter(start + "body\n")
        assert block is None, start
        assert body == start + "body\n"


def test_an_unterminated_block_is_not_frontmatter():
    text = "---\ntitle: nope\nno closing marker\n"
    block, body = split_frontmatter(text)
    assert block is None
    assert body == text


def test_an_empty_block_is_frontmatter():
    block, body = split_frontmatter("---\n---\nbody\n")
    assert block == ""
    assert body == "body\n"
    assert load_frontmatter("---\n---\nbody\n") == ({}, "body\n")


def test_no_frontmatter_means_the_whole_text_is_body():
    text = "just a note\n"
    assert split_frontmatter(text) == (None, text)
    assert load_frontmatter(text) == ({}, text)


# --- the writer --------------------------------------------------------------


def test_scalars_render_as_yaml_the_subset_can_read():
    assert dump_scalar(True) == "true"
    assert dump_scalar(False) == "false"
    assert dump_scalar(None) == "null"
    assert dump_scalar(3) == "3"
    assert dump_scalar(1.5) == "1.5"
    # Plain text stays plain; anything YAML could misread is quoted.
    assert dump_scalar("plain") == "plain"
    assert dump_scalar("needs: quoting") == '"needs: quoting"'
    assert dump_scalar("2026-01-02") == '"2026-01-02"'
    assert dump_scalar("1234") == '"1234"'
    assert dump_scalar("true") == '"true"'


def test_quoting_escapes_the_characters_that_used_to_corrupt_a_note():
    assert dump_frontmatter({"title": 'He said "hi"'}) == (
        '---\ntitle: "He said \\"hi\\""\n---'
    )
    assert dump_frontmatter({"title": "back\\slash"}) == (
        '---\ntitle: "back\\\\slash"\n---'
    )
    assert dump_frontmatter({"title": "a: b # c"}) == '---\ntitle: "a: b # c"\n---'
    assert dump_frontmatter({"title": "- leading dash"}) == (
        '---\ntitle: "- leading dash"\n---'
    )


def test_a_multiline_string_becomes_a_block_scalar():
    assert dump_frontmatter({"note": "line one\nline two"}) == (
        "---\nnote: |-\n  line one\n  line two\n---"
    )
    assert dump_frontmatter({"note": "keep the newline\n"}) == (
        "---\nnote: |\n  keep the newline\n---"
    )


def test_lists_render_in_flow_style():
    assert dump_frontmatter({"tags": ["alpha", "beta"]}) == "---\ntags: [alpha, beta]\n---"
    assert dump_frontmatter({"tags": ["a, b", "c"]}) == '---\ntags: ["a, b", c]\n---'


def test_bools_ints_floats_and_none_go_bare():
    block = dump_frontmatter({"agent": True, "n": 3, "f": 1.5, "nothing": None})
    assert block == "---\nagent: true\nn: 3\nf: 1.5\nnothing: null\n---"


# --- round-trip (the card's AC) ----------------------------------------------


def _doc(mapping) -> str:
    return dump_frontmatter(mapping) + "\n\nbody text\n"


def test_a_dumped_block_reads_back_identically():
    data = {
        "title": 'A "quoted" title: with # markers',
        "type": "permanent",
        "tags": ["alpha", "b, c", 'd"e'],
        "created": "2026-01-02",
        "agent": True,
        "importance": 0.7,
        "count": 4,
        "missing": None,
        "multi": "first line\nsecond line",
    }
    metadata, body = load_frontmatter(_doc(data))
    assert metadata == data
    assert body.strip() == "body text"


def test_random_titles_and_tags_round_trip():
    """The card's property test: arbitrary text survives the writer + reader."""
    rng = random.Random(602)
    alphabet = list('abc XYZ 019.:#-_"\'\\[]{}!|^,()&*?/@`~%') + ["\n", "\t", "—", "é"]
    for _ in range(300):
        title = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        tags = [
            "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
            for _ in range(rng.randint(0, 4))
        ]
        data = {"title": title, "tags": tags}
        metadata, _ = load_frontmatter(_doc(data))
        assert metadata == data, (title, tags, metadata)


@needs_yaml
def test_the_writer_emits_yaml_pyyaml_reads_identically():
    import yaml  # noqa: PLC0415

    data = {
        "title": 'A "quoted" # title',
        "tags": ["a", "b, c"],
        "agent": True,
        "n": 3,
        "f": 1.5,
        "nothing": None,
        "multi": "one\ntwo",
    }
    block = dump_frontmatter(data)
    assert yaml.safe_load(block[4:-3]) == data


@needs_yaml
def test_the_reader_falls_back_to_the_subset_parser():
    """PyYAML is preferred, but a block it cannot parse still reads: the
    subset parser is the safety net, and it must agree on plain YAML."""
    from em.vault import frontmatter  # noqa: PLC0415

    block = 'title: "T"\ntags: [a, b]\nagent: true\n'
    assert frontmatter._parse_subset(block) == {
        "title": "T",
        "tags": ["a", "b"],
        "agent": True,
    }


def test_the_subset_parser_handles_single_quotes_and_block_lists():
    from em.vault import frontmatter  # noqa: PLC0415

    block = "title: 'it''s quoted'\naliases:\n  - one\n  - two\n"
    assert frontmatter._parse_subset(block) == {
        "title": "it's quoted",
        "aliases": ["one", "two"],
    }


def test_an_unquoted_date_reads_as_a_string_not_a_date_object():
    """A hand-written `updated: 2026-01-02` must stay a string: the vault's
    callers do `date.fromisoformat(note.updated)`, and YAML's own typing would
    otherwise turn a hand edit into a TypeError."""
    metadata, _ = load_frontmatter("---\nupdated: 2026-01-02\n---\nbody\n")
    assert metadata["updated"] == "2026-01-02"
    assert isinstance(metadata["updated"], str)


@needs_yaml
def test_the_subset_parser_agrees_with_pyyaml_on_the_writers_output():
    """The fallback is only a fallback if it reads what the writer writes the
    same way PyYAML does — including the block-scalar chomping and the quoting
    edge cases."""
    import yaml  # noqa: PLC0415

    from em.vault import frontmatter  # noqa: PLC0415

    data = {
        "title": 'A "quoted" title: with # markers',
        "tags": ["alpha", "b, c", 'd"e'],
        "agent": True,
        "importance": 0.7,
        "count": 4,
        "missing": None,
        "multi": "first line\nsecond line",
        "kept": "trailing newline\n",
    }
    body = dump_frontmatter(data)[4:-3]
    assert frontmatter._parse_subset(body) == yaml.safe_load(body) == data


# --- wikilinks ---------------------------------------------------------------


def test_wikilinks_parse_every_documented_form():
    text = "See [[Target]] and [[Target|An Alias]] and [[Target#Heading]] "
    text += "and [[Target^block1]] and ![[Embedded Note]]."
    links = parse_wikilinks(text)
    assert [w.target for w in links] == [
        "Target",
        "Target",
        "Target",
        "Target",
        "Embedded Note",
    ]
    assert links[0].alias == "" and links[0].heading == "" and links[0].block == ""
    assert links[1].alias == "An Alias"
    assert links[2].heading == "Heading"
    assert links[3].block == "block1"
    assert links[4].embed is True
    assert links[0].embed is False


def test_an_alias_heading_and_block_can_combine():
    (link,) = parse_wikilinks("[[Target#Heading^blk|Alias]]")
    assert (link.target, link.heading, link.block, link.alias) == (
        "Target",
        "Heading",
        "blk",
        "Alias",
    )


def test_text_without_wikilinks_parses_to_nothing():
    assert parse_wikilinks("no links, [not one], [[unclosed") == []


def test_wikilink_raw_is_the_matched_text():
    (link,) = parse_wikilinks("x [[T|A]] y")
    assert link.raw == "[[T|A]]"
    assert isinstance(link, Wikilink)


# --- the v2 shim -------------------------------------------------------------


def test_note_frontmatter_block_keeps_plain_text_plain():
    note = Note(
        path=Path("Infrastructure/test.md"),
        title="Test Title",
        body="Body.",
        tags=["tag1"],
        domain="Infrastructure",
        note_type="permanent",
        source="agent",
        created="2026-01-02",
        agent=True,
    )
    block = note.to_frontmatter_block()
    assert block.splitlines()[0] == DELIMITER
    assert "title: Test Title" in block
    assert "tags: [tag1]" in block
    assert "type: permanent" in block
    assert 'created: "2026-01-02"' in block  # date-like, so quoted
    assert "agent: true" in block


def test_a_note_with_a_quote_or_newline_in_the_title_no_longer_corrupts(tmp_path):
    vault = Vault(tmp_path)
    (tmp_path / "Knowledge").mkdir()
    path = vault.write_note(
        "Knowledge",
        'He said "go"\nand left',
        "Body text.",
        domain="Knowledge",
        note_type="permanent",
    )
    note = vault.read_note(path)
    assert note.title == 'He said "go"\nand left'
    assert note.body == "Body text."


def test_read_frontmatter_ignores_a_delimiter_in_the_body(tmp_path):
    vault = Vault(tmp_path)
    (tmp_path / "Knowledge").mkdir()
    text = '---\ntitle: "Real Title"\n---\nbody\n\n---\n\nmore body\n'
    (tmp_path / "Knowledge" / "n.md").write_text(text, encoding="utf-8")
    fm = vault.read_frontmatter(tmp_path / "Knowledge" / "n.md")
    assert fm["title"] == "Real Title"
    note = vault.read_note(Path("Knowledge/n.md"))
    assert "---" in note.body and "more body" in note.body


def test_vault_extract_wikilinks_strips_an_alias():
    vault = Vault(Path("/nonexistent-vault-root"))
    assert vault.extract_wikilinks("See [[Target|Alias]] and [[Plain]].") == [
        "Target",
        "Plain",
    ]


def test_read_frontmatter_without_a_block_is_empty(tmp_path):
    vault = Vault(tmp_path)
    path = tmp_path / "plain.md"
    path.write_text("no frontmatter here\n", encoding="utf-8")
    assert vault.read_frontmatter(path) == {}
