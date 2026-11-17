"""What each Claude call costs, from its token usage. Prices are USD per million tokens.

Source: Anthropic's pricing page (checked Nov 2026). Haiku 5.5 is priced by prompt length: when a
single request's prompt is over 100K tokens, every rate for that request is 5x. That's why cost is
worked out per call, never from daily totals."""
from __future__ import annotations

import logging
from decimal import Decimal

log = logging.getLogger(__name__)

PRICES: dict[str, dict[str, Decimal]] = {
    "claude-haiku-5-5": {
        "input": Decimal("0.10"), "output": Decimal("0.50"),
        "cache_read": Decimal("0.01"), "cache_write": Decimal("0.125"),
        "long_prompt_tokens": Decimal(100_000), "long_multiplier": Decimal(5),
    },
}
MILLION = Decimal(1_000_000)


def _prices_for(model: str) -> dict[str, Decimal] | None:
    for name, prices in PRICES.items():
        if model == name or model.startswith(name + "-"):   # also matches dated ids like ...-20261007
            return prices
    return None


def call_cost(model: str, input_tokens: int, output_tokens: int,
              cache_read: int = 0, cache_write: int = 0) -> Decimal:
    """Cost of one model call. input_tokens is the full prompt (it already includes cached tokens)."""
    p = _prices_for(model)
    if p is None:
        log.warning("No price for model %r; recording $0", model)
        return Decimal(0)
    uncached = max(int(input_tokens) - int(cache_read) - int(cache_write), 0)
    cost = (uncached * p["input"] + int(output_tokens) * p["output"]
            + int(cache_read) * p["cache_read"] + int(cache_write) * p["cache_write"]) / MILLION
    if input_tokens > p["long_prompt_tokens"]:
        cost *= p["long_multiplier"]
    return cost.quantize(Decimal("0.000001"))