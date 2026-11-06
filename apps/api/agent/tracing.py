"""Local trace log: a LangChain callback handler that writes linked events to trace_events.

LangChain gives every LLM call and tool call its own run_id plus a parent_run_id. We record
LLM/tool events and skip LangGraph's internal node chains, re-pointing each event's parent to
its nearest *recorded* ancestor (the root run, a subagent, etc.) so the trace tree stays readable."""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from storage import db

log = logging.getLogger(__name__)

MEMORY_TOOLS = {"recall_memory", "remember"}
SKILL_TOOLS = {"load_skill"}
SUBAGENT_TOOLS = {"delegate_news_analysis"}
PREVIEW_CHARS = 2000


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def content_to_text(content: Any) -> str:
    """Flatten message/tool content (str, list of content blocks, or message) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if hasattr(content, "content"):
        return content_to_text(content.content)
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
            else:
                parts.append(str(b))
        return "\n".join(p for p in parts if p)
    return str(content)


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + " ...[truncated]"


def _looks_like_error(text: str) -> bool:
    """Error JSON, an 'Error:' string, or an empty result all count as failures."""
    if not text.strip():
        return True
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text.startswith("Error:")
    if obj in ({}, []):
        return True
    return isinstance(obj, dict) and "error" in obj


class TraceHandler(BaseCallbackHandler):
    run_inline = True     # write events in order, on the calling thread
    raise_error = False   # tracing must never break a run

    def __init__(self, root_run_id: str, user_id: int | None, mcp_tool_names: set[str] | None = None):
        self.root = root_run_id
        self.user_id = user_id
        self.mcp_tools = mcp_tool_names or set()
        self._parent_of: dict[str, str | None] = {}
        self._recorded: set[str] = {root_run_id}
        self._open: dict[str, dict] = {}

    # ---- linking ----
    def _logical_parent(self, parent_run_id) -> str:
        pid = str(parent_run_id) if parent_run_id else None
        hops = 0
        while pid and pid not in self._recorded and hops < 200:
            pid = self._parent_of.get(pid)
            hops += 1
        return pid or self.root

    def _tool_type(self, name: str) -> str:
        if name in self.mcp_tools:
            return "mcp"
        if name in MEMORY_TOOLS:
            return "memory"
        if name in SKILL_TOOLS:
            return "skill"
        if name in SUBAGENT_TOOLS:
            return "subagent"
        return "tool"

    def _start(self, run_id, parent_run_id, event_type: str, name: str, input: Any) -> None:
        rid = str(run_id)
        self._parent_of[rid] = str(parent_run_id) if parent_run_id else None
        self._open[rid] = {
            "event_type": event_type, "name": name, "input": input,
            "parent": self._logical_parent(parent_run_id),
            "started_at": now_iso(), "t0": time.perf_counter(),
        }
        self._recorded.add(rid)  # children that finish before us still link to us

    def _end(self, run_id, output: Any = None, status: str = "ok", error: str | None = None) -> None:
        ev = self._open.pop(str(run_id), None)
        if not ev:
            return
        try:
            db.log_trace_event(
                run_id=str(run_id), parent_run_id=ev["parent"], root_run_id=self.root,
                user_id=self.user_id, event_type=ev["event_type"], name=ev["name"],
                input=ev["input"], output=output, status=status, error=error,
                started_at=ev["started_at"], ended_at=now_iso(),
                duration_ms=round((time.perf_counter() - ev["t0"]) * 1000, 1),
            )
        except Exception:  # tracing must never break a run, but a lost event should be visible
            log.warning("Failed to record trace event %s (%s)", ev["name"], ev["event_type"], exc_info=True)

    # ---- chains: only remember parentage ----
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self._parent_of[str(run_id)] = str(parent_run_id) if parent_run_id else None

    # ---- LLM calls ----
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        params = kwargs.get("invocation_params") or {}
        model = params.get("model") or params.get("model_name") or "llm"
        msgs = messages[0] if messages else []
        last = msgs[-1] if msgs else None
        self._start(run_id, parent_run_id, "llm", model, {
            "n_messages": len(msgs),
            "last_message_type": getattr(last, "type", None),
            "last_message": _preview(content_to_text(getattr(last, "content", "")), 500),
        })

    def on_llm_end(self, response, *, run_id, **kwargs):
        out: dict[str, Any] = {}
        status, error = "ok", None
        try:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            out["text"] = _preview(content_to_text(msg.content if msg is not None else gen.text), 1500)
            if msg is not None:
                out["tool_calls"] = [{"name": tc["name"], "args": tc["args"]}
                                     for tc in (getattr(msg, "tool_calls", None) or [])]
                usage = getattr(msg, "usage_metadata", None)
                if usage:
                    out["usage"] = {k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")}
                out["stop_reason"] = (getattr(msg, "response_metadata", None) or {}).get("stop_reason")
                if out["stop_reason"] == "max_tokens":
                    status, error = "error", "Output truncated (stop_reason=max_tokens)"
        except Exception as e:
            out["parse_error"] = str(e)
        self._end(run_id, out, status=status, error=error)
    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=repr(error))

    # ---- tools (local + MCP) ----
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self._start(run_id, parent_run_id, self._tool_type(name), name,
                    inputs if inputs is not None else input_str)

    def on_tool_end(self, output, *, run_id, **kwargs):
        text = content_to_text(output)
        self._end(run_id, _preview(text), status="error" if _looks_like_error(text) else "ok")

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=repr(error))