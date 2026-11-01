"""Which bare-name HIL rules the migration rewrites to a server-scoped key, and which it reports."""

import pytest
from scripts.migrate_hil_overrides_to_scoped_keys import KeyPlan, migrated_rules, plan_keys

from app.models.hil_models import HILPreferences

SERVERS = {
    "posthog": frozenset({"delete_item", "query"}),
    "linear": frozenset({"delete_item", "create_issue"}),
    "notion": frozenset({"search"}),
}
REGISTRY = frozenset({"search", "GMAIL_SEND_EMAIL"})


@pytest.mark.unit
class TestPlanKeys:
    def test_a_name_on_exactly_one_connected_server_is_rewritten_to_its_scoped_key(self) -> None:
        plan = plan_keys(["query", "create_issue"], SERVERS, REGISTRY)
        assert plan == KeyPlan(
            rewrites={"query": "mcp:posthog:query", "create_issue": "mcp:linear:create_issue"},
            ambiguous={},
        )

    def test_a_name_on_several_servers_is_reported_and_left_alone(self) -> None:
        plan = plan_keys(["delete_item"], SERVERS, REGISTRY)
        assert plan == KeyPlan(rewrites={}, ambiguous={"delete_item": ["linear", "posthog"]})

    def test_a_registry_tool_name_is_left_alone_even_when_a_server_has_it(self) -> None:
        assert plan_keys(["search", "GMAIL_SEND_EMAIL"], SERVERS, REGISTRY) == KeyPlan({}, {})

    def test_an_already_scoped_or_unknown_key_is_left_alone(self) -> None:
        assert plan_keys(["mcp:posthog:query", "nowhere"], SERVERS, REGISTRY) == KeyPlan({}, {})


@pytest.mark.unit
class TestMigratedRules:
    def test_overrides_and_never_auto_rules_move_to_their_scoped_keys(self) -> None:
        prefs = HILPreferences(
            mode="auto",
            tool_overrides={"query": False, "delete_item": True, "GMAIL_SEND_EMAIL": True},
            never_auto_tools=["query", "search"],
        )
        plan = plan_keys([*prefs.tool_overrides, *prefs.never_auto_tools], SERVERS, REGISTRY)

        overrides, never_auto = migrated_rules(prefs, plan)

        assert overrides == {
            "mcp:posthog:query": False,
            "delete_item": True,
            "GMAIL_SEND_EMAIL": True,
        }
        assert never_auto == ["mcp:posthog:query", "search"]

    def test_an_existing_scoped_rule_wins_over_the_bare_one_it_would_replace(self) -> None:
        prefs = HILPreferences(
            tool_overrides={"query": False, "mcp:posthog:query": True},
            never_auto_tools=["mcp:posthog:query", "query"],
        )
        plan = plan_keys([*prefs.tool_overrides, *prefs.never_auto_tools], SERVERS, REGISTRY)

        overrides, never_auto = migrated_rules(prefs, plan)

        assert overrides == {"mcp:posthog:query": True}
        assert never_auto == ["mcp:posthog:query"]
