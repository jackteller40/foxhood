"""Trace log: a LangChain callback handler that collects linked events for one agent run.

LangChain gives every LLM call and tool call its own run_id plus a parent_run_id. We record
LLM/tool events and skip LangGraph's internal node chains, re-pointing each event's parent to
its nearest *recorded* ancestor (the root run, a subagent, etc.) so the trace tree stays readable.

Events are buffered in memory and saved (encrypted) once, when the run ends: one DB write per run
instead of one per event. Token usage is totalled per model at the same time.

If the runner passes an `emit` callback, the handler also sends small live events for the main
agent only (subagent internals stay hidden): answer tokens, tools starting/finishing, denials."""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from db.models import utcnow

MEMORY_TOOLS = {"recall_memory", "remember"}
SKILL_TOOLS = {"load_skill"}
SUBAGENT_TOOLS = {"delegate_news_analysis"}
PREVIEW_CHARS = 2000

EventSink = Callable[[dict], None]   # receives live events; must not block (e.g. queue.put_nowait)

# The handler for the run in progress, so graph nodes (the permission gate) can add events
# without threading the handler through every function. asyncio tasks inherit it automatically.
_active: ContextVar[TraceHandler | None] = ContextVar("foxhood_trace", default=None)


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


@contextmanager
def activate(handler: TraceHandler) -> Iterator[None]:
    token = _active.set(handler)
    try:
        yield
    finally:
        _active.reset(token)


def record_event(event_type: str, name: str, *, input: Any = None, output: Any = None,
                 status: str = "ok", error: str | None = None) -> None:
    """Add a one-off event (e.g. a permission decision) to the active run's trace, if any."""
    handler = _active.get()
    if handler is not None:
        handler.add_event(event_type, name, input=input, output=output, status=status, error=error)
        if event_type == "permission" and status == "denied":
            handler.emit({"type": "denied", "name": name, "reason": (output or {}).get("reason")})


class TraceHandler(BaseCallbackHandler):
    run_inline = True     # handle events in order, on the calling thread
    raise_error = False   # tracing must never break a run

    def __init__(self, root_run_id: str, mcp_tool_names: set[str] | None = None, emit: EventSink | None = None):
        self.root = root_run_id
        self.mcp_tools = mcp_tool_names or set()
        self._emit = emit
        self._last_chunk = None
        self.events: list[dict] = []               # finished events, ready for UserRepo.add_trace_events
        self.usage: dict[str, list[int]] = {}      # model -> [input_tokens, output_tokens]
        self._parent_of: dict[str, str | None] = {}
        self._recorded: set[str] = {root_run_id}
        self._open: dict[str, dict] = {}

    # ---- live events ----
    def emit(self, event: dict) -> None:
        """Send a live event, if anyone is listening. A broken listener never breaks the run."""
        if self._emit is None:
            return
        try:
            self._emit(event)
        except Exception:
            self._emit = None   # stop sending to a listener that failed (e.g. browser went away)

    def _is_top_level(self, run_id) -> bool:
        ev = self._open.get(str(run_id))
        return ev is not None and ev["parent"] == self.root

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

    def add_event(self, event_type: str, name: str, *, input: Any = None, output: Any = None,
                  status: str = "ok", error: str | None = None) -> None:
        now = utcnow()
        self.events.append({
            "run_id": str(uuid.uuid4()), "parent_run_id": self.root, "root_run_id": self.root,
            "event_type": event_type, "name": name, "status": status,
            "input": input, "output": output, "error": error,
            "started_at": now, "ended_at": now, "duration_ms": 0.0,
        })

    def _start(self, run_id, parent_run_id, event_type: str, name: str, input: Any) -> None:
        rid = str(run_id)
        self._parent_of[rid] = str(parent_run_id) if parent_run_id else None
        self._open[rid] = {
            "event_type": event_type, "name": name, "input": input,
            "parent": self._logical_parent(parent_run_id),
            "started_at": utcnow(), "t0": time.perf_counter(),
        }
        self._recorded.add(rid)  # children that finish before us still link to us

    def _end(self, run_id, output: Any = None, status: str = "ok", error: str | None = None) -> dict | None:
        ev = self._open.pop(str(run_id), None)
        if not ev:
            return None
        self.events.append({
            "run_id": str(run_id), "parent_run_id": ev["parent"], "root_run_id": self.root,
            "event_type": ev["event_type"], "name": ev["name"], "status": status,
            "input": ev["input"], "output": output, "error": error,
            "started_at": ev["started_at"], "ended_at": utcnow(),
            "duration_ms": round((time.perf_counter() - ev["t0"]) * 1000, 1),
        })
        return ev

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
        model, usage = None, None
        try:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            out["text"] = _preview(content_to_text(msg.content if msg is not None else gen.text), 1500)
            if msg is not None:
                out["tool_calls"] = [{"name": tc["name"], "args": tc["args"]}
                                     for tc in (getattr(msg, "tool_calls", None) or [])]
                meta = getattr(msg, "response_metadata", None) or {}
                model = meta.get("model_name") or meta.get("model")
                usage = getattr(msg, "usage_metadata", None)
                if usage:
                    out["usage"] = {k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")}
                out["stop_reason"] = meta.get("stop_reason")
                if out["stop_reason"] == "max_tokens":
                    status, error = "error", "Output truncated (stop_reason=max_tokens)"
        except Exception as e:
            out["parse_error"] = str(e)
        ev = self._end(run_id, out, status=status, error=error)
        if usage:
            key = str(model or (ev or {}).get("name") or "llm")
            totals = self.usage.setdefault(key, [0, 0])
            totals[0] += int(usage.get("input_tokens") or 0)
            totals[1] += int(usage.get("output_tokens") or 0)

    def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        if self._emit is None or not self._is_top_level(run_id):
            return
        if chunk is not None:
            # langchain-anthropic reports each chunk twice (once itself, once via the base class).
            if chunk is self._last_chunk:
                return
            self._last_chunk = chunk
            msg = getattr(chunk, "message", None)
            text = content_to_text(msg.content) if msg is not None else getattr(chunk, "text", "")
        else:
            text = content_to_text(token)
        if text:
            self.emit({"type": "token", "text": text})

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, status="error", error=repr(error))

    # ---- tools (local + MCP) ----
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        kind = self._tool_type(name)
        self._start(run_id, parent_run_id, kind, name, inputs if inputs is not None else input_str)
        if self._is_top_level(run_id):
            self.emit({"type": "tool_start", "id": str(run_id), "name": name, "kind": kind})

    def on_tool_end(self, output, *, run_id, **kwargs):
        text = content_to_text(output)
        self._tool_done(run_id, _preview(text), "error" if _looks_like_error(text) else "ok")

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._tool_done(run_id, None, "error", repr(error))

    def _tool_done(self, run_id, output: Any, status: str, error: str | None = None) -> None:
        top = self._is_top_level(run_id)
        ev = self._end(run_id, output, status=status, error=error)
        if top and ev:
            self.emit({"type": "tool_end", "id": str(run_id), "name": ev["name"], "status": status})