"""The permission policy on its own (no LLM, no network)."""
import pytest

from agent.permissions import Policy


@pytest.fixture(scope="module")
def policy():
    return Policy.load()


@pytest.mark.parametrize("tool, args, action", [
    ("get_positions", {}, "allow"),
    ("submit_trade_order", {"ticker": "NVDA", "side": "sell", "quantity": 100}, "deny"),
    ("remember", {"content": "my account number is 1234-5678-9012"}, "deny"),
    ("remember", {"content": "my SSN is 123-45-6789"}, "deny"),
    ("remember", {"content": "Never recommend crypto stocks"}, "ask"),
    ("add_holding", {"ticker": "AAPL", "purchase_date": "2024-01-03", "amount": 250000}, "deny"),
    ("delete_everything", {}, "deny"),
])
def test_policy_decisions(policy, tool, args, action):
    assert policy.check(tool, args).action == action


def test_unattended_turns_ask_into_deny():
    assert Policy.load(unattended=True).check("remember", {"content": "x"}).action == "deny"