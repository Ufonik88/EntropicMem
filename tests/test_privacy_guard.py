"""EM-118 (H1): interim gateway privacy guard (owner/guest separation).

Config ``owner_user_ids``. When the gateway supplies a user_id that is not
in the (non-empty) owner list, the session is "guest mode": prefetch
excludes sensitive/secret facts and ``guest_hidden_domains`` (default
People/Finance), Core Memory injects Persona only (never User Profile),
write tools stamp user:<id> + source=guest_tool, and patch_core is
refused. Owners are unaffected. Empty owner_user_ids with a gateway
user_id logs a one-time warning (shared-pool limitation, full per-user
scoping is S4).
"""

import logging

from fake_host import FakeHost

OWNER = "user_alice"
GUEST = "user_bob"


def _provider(make_provider, home_a, user_id, **cfg):
    cfg.setdefault("owner_user_ids", [OWNER])
    provider = make_provider(cfg)
    host = FakeHost(
        provider, hermes_home=home_a, agent_identity="homeA",
        init_kwargs={"user_id": user_id, "chat_type": "private"},
    )
    host.start()
    return provider, host


def _prefetch(provider, query="the user lives in cape town near the mountain"):
    return provider.prefetch(query)


class TestGuestPrefetchExclusions:
    def test_guest_never_gets_owner_people_facts(self, make_provider, home_a):
        owner, host_o = _provider(make_provider, home_a, OWNER)
        owner.handle_tool_call(
            "entropicmem_remember",
            {"content": "The user lives in Cape Town near the mountain",
             "domain": "People", "importance": 0.9},
        )
        host_o.shutdown()

        guest, host_g = _provider(make_provider, home_a, GUEST)
        block = _prefetch(guest)
        host_g.shutdown()
        assert "Cape Town" not in block, f"owner People fact leaked to guest: {block}"

    def test_owner_unaffected(self, make_provider, home_a):
        owner, host_o = _provider(make_provider, home_a, OWNER)
        owner.handle_tool_call(
            "entropicmem_remember",
            {"content": "The user lives in Cape Town near the mountain",
             "domain": "People", "importance": 0.9},
        )
        block = _prefetch(owner)
        host_o.shutdown()
        assert "Cape Town" in block, f"owner lost their own fact: {block}"

    def test_guest_never_gets_sensitive_or_secret(self, make_provider, home_a):
        owner, host_o = _provider(make_provider, home_a, OWNER)
        owner.handle_tool_call(
            "entropicmem_remember",
            {"content": "The deployment signing token rotates quarterly on friday",
             "domain": "Work", "importance": 0.9, "sensitivity": "secret"},
        )
        owner.handle_tool_call(
            "entropicmem_remember",
            {"content": "The vendor negotiation ceiling is forty thousand rand",
             "domain": "Work", "importance": 0.9, "sensitivity": "sensitive"},
        )
        host_o.shutdown()

        guest, host_g = _provider(make_provider, home_a, GUEST)
        block = _prefetch(
            guest, "the deployment signing token and the vendor negotiation ceiling"
        )
        host_g.shutdown()
        assert "signing token" not in block, f"secret fact leaked to guest: {block}"
        assert "negotiation ceiling" not in block, f"sensitive fact leaked to guest: {block}"


class TestGuestCoreMemory:
    def test_guest_gets_persona_never_profile(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a, GUEST)
        from vault import CoreMemory

        core = CoreMemory(home_a / "entropicmem" / "vault")
        core.patch("persona", "## Identity", "## Identity\nPersona marker unit-p-9")
        core.patch("user_profile", "## Facts", "## Facts\nProfile marker unit-u-9")
        block = provider.system_prompt_block()
        host.shutdown()
        assert "unit-p-9" in block, f"persona should be allowed for guests: {block}"
        assert "unit-u-9" not in block, f"User Profile leaked to guest: {block}"

    def test_owner_gets_both_core_sections(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a, OWNER)
        from vault import CoreMemory

        core = CoreMemory(home_a / "entropicmem" / "vault")
        core.patch("persona", "## Identity", "## Identity\nPersona marker unit-p-9")
        core.patch("user_profile", "## Facts", "## Facts\nProfile marker unit-u-9")
        block = provider.system_prompt_block()
        host.shutdown()
        assert "unit-p-9" in block and "unit-u-9" in block, (
            f"owner core injection incomplete: {block}"
        )


class TestGuestWriteStamping:
    def test_guest_writes_stamped(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a, GUEST)
        provider.handle_tool_call(
            "entropicmem_remember",
            {"content": "The guest prefers meetings after lunch on tuesdays",
             "domain": "Preferences"},
        )
        engine, err = provider._memory_engine()
        assert err is None, err
        with engine:
            row = engine.db.execute(
                "SELECT source, tags FROM facts WHERE content LIKE '%meetings after lunch%'"
            ).fetchone()
        host.shutdown()
        assert row is not None, "guest write did not land"
        assert row[0] == "guest_tool", f"guest write source not stamped: {row[0]!r}"
        assert f"user:{GUEST}" in (row[1] or ""), f"guest write tag missing: {row[1]!r}"

    def test_owner_writes_not_stamped(self, make_provider, home_a):
        provider, host = _provider(make_provider, home_a, OWNER)
        provider.handle_tool_call(
            "entropicmem_remember",
            {"content": "The owner prefers meetings after lunch on wednesdays",
             "domain": "Preferences"},
        )
        engine, err = provider._memory_engine()
        assert err is None, err
        with engine:
            row = engine.db.execute(
                "SELECT source, tags FROM facts WHERE content LIKE '%wednesdays%'"
            ).fetchone()
        host.shutdown()
        assert row[0] != "guest_tool", f"owner misclassified as guest: {row}"


class TestGuestPatchCoreRefused:
    def test_patch_core_refused_for_guest(self, make_provider, home_a):
        # core writes enabled for owners — the refusal below must come from
        # the GUEST check, not the default-off config
        provider, host = _provider(
            make_provider, home_a, GUEST, core_memory_writable=True,
        )
        out = provider.handle_tool_call(
            "entropicmem_patch_core",
            {"target": "persona", "old_text": "## Identity",
             "new_text": "## Identity\nguest should not write this"},
        )
        host.shutdown()
        assert "error" in out.lower() or "refus" in out.lower(), (
            f"guest patch_core not refused: {out}"
        )


class TestUnconfiguredWarning:
    def test_one_time_warning_without_owner_ids(self, make_provider, home_a, caplog):
        import plugins.entropicmem as emod

        # the warning is one-time PER PROCESS — reset the flag so this test
        # is order-independent (earlier gateway-user tests consume it)
        cls = emod.EntropicMemMemoryProvider
        had = getattr(cls, "_owner_warned", False)
        cls._owner_warned = False
        try:
            with caplog.at_level(logging.WARNING, logger="plugins.entropicmem"):
                for _ in range(2):
                    provider = make_provider({})  # owner_user_ids empty
                    host = FakeHost(
                        provider, hermes_home=home_a, agent_identity="homeA",
                        init_kwargs={"user_id": GUEST, "chat_type": "private"},
                    )
                    host.start()
                    host.shutdown()
            warns = [r for r in caplog.records if "owner_user_ids" in r.message]
            assert warns, (
                f"no warning about empty owner_user_ids: "
                f"{[r.message for r in caplog.records]}"
            )
            assert len(warns) == 1, f"warning must be one-time: {len(warns)}"
        finally:
            cls._owner_warned = had
