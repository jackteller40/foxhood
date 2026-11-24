"""Small, readable checks on an agent run. Each returns (passed, description)."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage

from agent.runner import AgentResult


@dataclass
class Run:
    result: AgentResult
    truth: dict                          # ground-truth numbers computed from the real tools

    @property
    def answer(self) -> str:
        return self.result.answer or ""

    def calls(self) -> list[tuple[str, dict]]:
        return [(tc["name"], tc.get("args") or {}) for m in self.result.messages if isinstance(m, AIMessage)
                for tc in (m.tool_calls or [])]


Check = Callable[[Run], tuple[bool, str]]
NUMBER = re.compile(r"(?<![\w.])[-−]?\$?\d[\d,]*(?:\.\d+)?\s*[kK]?(?![\w])")


def numbers_in(text: str) -> list[float]:
    out = []
    for raw in NUMBER.findall(text):
        s = raw.replace("$", "").replace(",", "").replace("−", "-").strip()
        mult = 1000 if s[-1:] in "kK" else 1
        try:
            out.append(abs(float(s.rstrip("kK").strip())) * mult)
        except ValueError:
            continue
    return out


def called(name: str, where: Callable[[dict], bool] | None = None, label: str = "") -> Check:
    def check(r: Run):
        ok = any(n == name and (where is None or where(a)) for n, a in r.calls())
        return ok, f"called {name}{' ' + label if label else ''}"
    return check


def not_called(name: str) -> Check:
    return lambda r: (all(n != name for n, _ in r.calls()), f"did not call {name}")


def mentions(*words: str, every: bool = True) -> Check:
    def check(r: Run):
        text = r.answer.lower()
        hits = [w for w in words if w.lower() in text]
        ok = len(hits) == len(words) if every else bool(hits)
        return ok, f"mentions {' and '.join(words) if every else ' or '.join(words)}"
    return check


def number(key: str, tolerance_pct: float = 1.0, minimum: float = 0.6) -> Check:
    """The answer states the ground-truth number `key` (any sign, within tolerance or rounding)."""
    def check(r: Run):
        want = abs(float(r.truth[key]))
        ok = any(abs(x - want) <= max(want * tolerance_pct / 100, minimum) for x in numbers_in(r.answer))
        return ok, f"states {key} = {want:,.2f}"
    return check


def status(expected: str) -> Check:
    return lambda r: (r.result.status == expected, f"run status is {expected}")


def asks_approval(tool: str, where: Callable[[dict], bool] | None = None) -> Check:
    def check(r: Run):
        ok = r.result.status == "paused" and any(
            p.get("tool") == tool and (where is None or where(p.get("args") or {})) for p in r.result.pending)
        return ok, f"paused for approval of {tool}"
    return check


def footer() -> Check:
    return lambda r: (r.answer.rstrip().endswith("Not financial advice."), "ends with 'Not financial advice.'")


def no_made_up_percentages() -> Check:
    """For questions the tools can't answer: no specific % figures should appear."""
    return lambda r: ("%" not in r.answer, "states no percentages")
