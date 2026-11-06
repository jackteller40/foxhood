"""Permission policy: every tool call is checked against config/permissions.yaml BEFORE it runs.

Order: deny list -> argument/content rules -> unattended mode -> ask -> allow -> default."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from core.config import ROOT
from datasources import market

POLICY_PATH = ROOT / "config" / "permissions.yaml"


@dataclass(frozen=True)
class Decision:
    action: str   # "allow" | "ask" | "deny"
    rule: str     # which rule matched, e.g. "deny:submit_trade_order"
    reason: str


def _ticker_exists(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    if not t or len(t) > 10:
        return False
    try:
        return not market.get_price_history(t, start=date.today() - timedelta(days=10)).empty
    except Exception:
        return False


def _estimated_value(args: dict) -> float | None:
    if args.get("amount") is not None:
        return float(args["amount"])
    if args.get("shares") is not None:
        try:
            return float(args["shares"]) * market.get_quote(str(args.get("ticker", "")))["price"]
        except Exception:
            return None
    return None


class Policy:
    def __init__(self, data: dict, unattended: bool = False):
        self.default = data.get("default", "deny")
        self.allow = set(data.get("allow") or [])
        self.ask = dict(data.get("ask") or {})
        self.deny = dict(data.get("deny") or {})
        rules = data.get("rules") or {}
        self.max_holding_value = float(rules.get("max_holding_value_usd", 100_000))
        self.validate_ticker_for = set(rules.get("validate_ticker_for") or [])
        self.sensitive = [(name, re.compile(rx)) for name, rx in (rules.get("sensitive_content") or {}).items()]
        self.max_tool_calls = int((data.get("budget") or {}).get("max_tool_calls_per_run", 40))
        self.unattended = unattended

    @classmethod
    def load(cls, path: Path = POLICY_PATH, unattended: bool = False) -> Policy:
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {}, unattended=unattended)

    def check(self, tool: str, args: dict | None) -> Decision:
        args = args or {}

        if tool in self.deny:
            return Decision("deny", f"deny:{tool}", self.deny[tool])

        if tool == "remember":
            text = str(args.get("content", ""))
            for name, rx in self.sensitive:
                if rx.search(text):
                    return Decision("deny", f"content:{name}",
                                    f"The memory appears to contain sensitive data ({name.replace('_', ' ')}). "
                                    "Sensitive identifiers are never stored.")

        if tool == "add_holding":
            value = _estimated_value(args)
            if value is not None and value > self.max_holding_value:
                return Decision("deny", "arg:max_holding_value",
                                f"A holding worth about ${value:,.0f} exceeds the "
                                f"${self.max_holding_value:,.0f} limit (likely a typo).")

        if tool in self.validate_ticker_for and not _ticker_exists(args.get("ticker", "")):
            return Decision("deny", "arg:unknown_ticker",
                            f"Ticker '{args.get('ticker')}' has no recent price data.")

        if tool in self.ask:
            if self.unattended:
                return Decision("deny", "unattended",
                                f"{self.ask[tool]} Nobody is present to approve it in an unattended run.")
            return Decision("ask", f"ask:{tool}", self.ask[tool])

        if tool in self.allow:
            return Decision("allow", f"allow:{tool}", "Read-only tool.")

        return Decision(self.default, "default", "Tool is not listed in the permission policy.")