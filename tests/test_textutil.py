"""EM-101 (H2): shared multimodal-safe message normalisation.

``message_text`` must accept any host message shape (str, dict, multipart
list, nested ``content`` payloads, None, junk) and return ``str`` without
ever raising — a single multimodal turn used to kill memory injection.
"""

import random

from textutil import message_text


def test_str_passthrough():
    assert message_text("hello there") == "hello there"


def test_none_is_empty():
    assert message_text(None) == ""


def test_dict_with_str_content():
    assert message_text({"role": "user", "content": "plain"}) == "plain"


def test_multipart_list_text_keys():
    parts = [
        {"type": "text", "text": "caption"},
        {"type": "input_text", "text": "from-input"},
        {"type": "output_text", "text": "from-output"},
        {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
    ]
    out = message_text({"role": "user", "content": parts})
    assert out == "caption from-input from-output"


def test_bare_list_of_parts():
    assert message_text([{"text": "a"}, {"input_text": "b"}]) == "a b"


def test_dict_with_nested_content():
    msg = {"role": "user", "content": {"content": [{"text": "deep"}]}}
    assert message_text(msg) == "deep"


def test_junk_shapes_are_empty_or_str():
    for junk in (42, 3.14, b"bytes", object(), {"type": "image"}, [[]], {"content": 7}):
        out = message_text(junk)
        assert isinstance(out, str)


def test_fuzz_never_raises():
    rng = random.Random(20260924)
    leaves = [None, "", "text", 1, 2.5, b"x", True, {"text": "t"}, {"input_text": "i"},
              {"output_text": "o"}, {"content": "c"}, {"type": "image"}, object(), set()]

    def build(depth=0):
        pick = rng.random()
        if depth > 4 or pick < 0.5:
            return rng.choice(leaves)
        if pick < 0.75:
            return [build(depth + 1) for _ in range(rng.randint(0, 3))]
        return {"content": build(depth + 1), "role": "user"}

    for _ in range(500):
        out = message_text(build())
        assert isinstance(out, str)
