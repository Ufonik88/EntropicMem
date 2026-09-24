"""EM-115 (G1): de-personalise product defaults.

- DEFAULT_DOMAINS is the generic seven (no employer/campaign/product names).
- prefetch_denied_sources is ["auto_extracted", "test"] only.
- Policy messages name no specific secrets-manager product.
- Region-specific PII (South African phone/ID) lives in opt-in locale
  packs; the default (empty) scans generic patterns only.
"""


from plugins.entropicmem import SMART_CONTEXT_DEFAULTS

import policy
import vault
from pii import scan_pii

GENERIC_DOMAINS = [
    "Knowledge", "People", "Projects", "Procedures",
    "Preferences", "Events", "Infrastructure",
]


class TestGenericDefaults:
    def test_default_domains_generic(self):
        assert vault.DEFAULT_DOMAINS == GENERIC_DOMAINS, (
            f"personalised domains in DEFAULT_DOMAINS: {vault.DEFAULT_DOMAINS}"
        )

    def test_prefetch_denied_sources_minimal(self):
        assert SMART_CONTEXT_DEFAULTS["prefetch_denied_sources"] == ["auto_extracted", "test"], (
            f"test-only sources leaked into product defaults: "
            f"{SMART_CONTEXT_DEFAULTS['prefetch_denied_sources']}"
        )

    def test_locale_packs_default_empty(self):
        assert SMART_CONTEXT_DEFAULTS.get("locale_packs") == [], (
            f"locale packs must default to opt-in empty: "
            f"{SMART_CONTEXT_DEFAULTS.get('locale_packs')}"
        )


class TestPolicyMessage:
    def test_no_product_name_in_policy_messages(self):
        action, reason = policy.evaluate_write("password=abc12345", domain="Work")
        assert action == "block"
        for product in ("vaultknox", "1password", "bitwarden", "lastpass", "keepass"):
            assert product not in (reason or "").lower(), (
                f"policy message names a secrets-manager product: {reason}"
            )


class TestLocalePacks:
    def test_generic_pii_detected_by_default(self):
        findings = scan_pii("reach me at jane.doe@example.com for the file")
        assert any(f.pii_type == "email" for f in findings), "generic email detection broken"

    def test_region_specific_off_by_default(self):
        text = "call me on 0821234567 or check id 8001015009087"
        assert not any(f.pii_type in ("phone", "id_number") for f in scan_pii(text)), (
            "region-specific PII detected despite empty locale packs"
        )

    def test_region_specific_opt_in(self):
        from pii import _raw_findings

        text = "call me on 0821234567 or check id 8001015009087"
        findings = scan_pii(text, locales=["za"])
        assert any(f.pii_type == "phone" for f in findings), (
            f"za phone pack not applied: {[f.pii_type for f in findings]}"
        )
        # id_number collides with generic phone_intl/credit_card on a bare
        # 13-digit run and the cluster-merge reports one type, so pin the
        # pack mechanics at raw level
        raw = {f.pii_type for f in _raw_findings(text, ["za"])}
        assert "id_number" in raw, f"za id_number pattern not applied: {raw}"
        assert "id_number" not in {f.pii_type for f in _raw_findings(text)}

    def test_engine_receives_locale_packs(self, make_provider, home_a):
        from fake_host import FakeHost

        provider = make_provider({"locale_packs": ["za"]})
        host = FakeHost(provider, hermes_home=home_a, agent_identity="homeA")
        host.start()
        engine, err = provider._memory_engine()
        assert err is None, err
        with engine:
            assert list(engine.pii_locales) == ["za"], (
                f"locale packs not wired into the engine: {engine.pii_locales}"
            )
        host.shutdown()
