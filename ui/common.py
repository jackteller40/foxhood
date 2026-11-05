"""Shared UI pieces: user picker, run footers, and the trace viewer."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from datasources.market import ET
from storage import db

LANGSMITH_URL = "https://smith.langchain.com"
TYPE_ICON = {"run": "▶️", "llm": "🧠", "tool": "🔧", "mcp": "🔌", "subagent": "🤖",
             "skill": "📘", "memory": "💾", "permission": "🛡️", "error": "❌"}
STATUS_ICON = {"ok": "✅", "error": "❌", "denied": "⛔", "pending": "⏸️", "paused": "⏸️",
               "approved": "👍", "rejected": "👎"}


@st.cache_resource
def _init_db() -> bool:
    db.init_db()
    if not db.list_users():
        from storage.seed_demo import seed
        seed()
    return True


def sidebar() -> dict:
    """User picker shared by every page. The choice is kept in session_state across pages."""
    _init_db()
    users = db.list_users()
    ids = [u["id"] for u in users]
    if st.session_state.get("user_id") not in ids:
        st.session_state["user_id"] = ids[0]
    names = {u["id"]: f"{u['name']} ({u['persona']})" for u in users}
    with st.sidebar:
        st.header("📈 Research agent")
        picked = st.selectbox("User", ids, index=ids.index(st.session_state["user_id"]), format_func=names.get)
        if picked != st.session_state["user_id"]:
            st.session_state["user_id"] = picked
            st.rerun()
        user = db.get_user(picked)
        st.caption(f"Risk: **{user['risk_tolerance']}** · Horizon: {user['horizon']}")
        st.caption("Interests: " + ", ".join(user["interests"]))
        st.divider()
        st.link_button("LangSmith traces", LANGSMITH_URL, icon="🔗")
        st.caption("Research only. Not financial advice.")
    return user


def flash(message: str | None = None) -> None:
    """Set a message to show after the next rerun, or show and clear the pending one."""
    if message is not None:
        st.session_state["_flash"] = message
    elif msg := st.session_state.pop("_flash", None):
        st.success(msg)


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).astimezone(ET).strftime("%b %d, %I:%M:%S %p")


def open_trace(run_id: str) -> None:
    st.session_state["trace_run_id"] = run_id
    st.switch_page("pages/4_Trace.py")


def trace_button(run_id: str | None, key: str, label: str = "View trace") -> None:
    if run_id and st.button(label, key=key, icon="🔍"):
        open_trace(run_id)


def _usage_tokens(e: dict) -> int:
    out = e.get("output")
    return ((out.get("usage") or {}).get("total_tokens") or 0) if isinstance(out, dict) else 0


def run_stats(events: list[dict]) -> dict:
    root = next((e for e in events if e["event_type"] == "run"), {}) or {}
    llm = [e for e in events if e["event_type"] == "llm"]
    return {
        "status": root.get("status", "?"),
        "duration_s": (root.get("duration_ms") or 0) / 1000,
        "llm_calls": len(llm),
        "tokens": sum(_usage_tokens(e) for e in llm),
        "tool_calls": sum(e["event_type"] in {"tool", "mcp", "memory", "skill", "subagent"} for e in events),
        "errors": sum(e["status"] == "error" for e in events),
        "denials": sum(e["status"] == "denied" for e in events),
    }


def run_footer(run_id: str, key: str) -> None:
    events = db.get_run_events(run_id)
    if not events:
        return
    s = run_stats(events)
    extra = (f" · {s['denials']} denied" if s["denials"] else "") + (f" · {s['errors']} errors" if s["errors"] else "")
    c1, c2 = st.columns([5, 1])
    c1.caption(f"{s['tool_calls']} tool calls · {s['llm_calls']} LLM calls · {s['tokens']:,} tokens · "
               f"{s['duration_s']:.1f}s{extra}")
    with c2:
        trace_button(run_id, key=key)


def _with_depth(events: list[dict]) -> list[tuple[int, dict]]:
    depth: dict[str, int] = {}
    out = []
    for e in events:
        d = 0 if e["event_type"] == "run" else depth.get(e["parent_run_id"], 0) + 1
        depth[e["run_id"]] = d
        out.append((d, e))
    return out


def _as_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _show(value) -> None:
    v = _as_json(value)
    if v is None:
        st.caption("-")
    elif isinstance(v, (dict, list)):
        st.json(v, expanded=False)
    else:
        st.code(str(v)[:4000], language=None)


def render_trace(run_id: str) -> None:
    events = db.get_run_events(run_id)
    if not events:
        st.info("No events recorded for this run.")
        return
    s = run_stats(events)
    cols = st.columns(6)
    cols[0].metric("Status", f"{STATUS_ICON.get(s['status'], '')} {s['status']}")
    cols[1].metric("Duration", f"{s['duration_s']:.1f}s")
    cols[2].metric("LLM calls", s["llm_calls"])
    cols[3].metric("Tokens", f"{s['tokens']:,}")
    cols[4].metric("Tool calls", s["tool_calls"])
    cols[5].metric("Errors / denials", f"{s['errors']} / {s['denials']}")

    rows = _with_depth(events)

    # Timeline: one bar per event, indented by nesting depth.
    df = pd.DataFrame([{
        "label": f"{i:02d} {'· ' * d}{e['event_type']}: {e['name']}",
        "type": e["event_type"], "status": e["status"],
        "start": pd.to_datetime(e["started_at"]),
        "end": pd.to_datetime(e["ended_at"] or e["started_at"]),
    } for i, (d, e) in enumerate(rows)])
    short = df["end"] <= df["start"] + pd.Timedelta(milliseconds=30)
    df.loc[short, "end"] = df.loc[short, "start"] + pd.Timedelta(milliseconds=30)  # keep instant events visible
    fig = px.timeline(df, x_start="start", x_end="end", y="label", color="type", hover_data=["status"])
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=max(260, 22 * len(df) + 80), margin=dict(l=0, r=0, t=10, b=0), legend_title_text=None)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Events")
    for d, e in rows:
        dur = f" · {e['duration_ms']:.0f} ms" if e["duration_ms"] is not None else ""
        indent = "\u3000" * d  # wide space; kept outside the f-string for Python 3.11
        label = (f"{indent}{TYPE_ICON.get(e['event_type'], '•')} {e['event_type']} · {e['name']} · "
                 f"{STATUS_ICON.get(e['status'], '')} {e['status']}{dur}")
        with st.expander(label, expanded=e["status"] in {"error", "denied"}):
            st.caption(f"run_id `{e['run_id']}` · parent `{e['parent_run_id'] or '-'}` · {fmt_time(e['started_at'])}")
            if e["error"]:
                st.error(e["error"])
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Input**")
                _show(e["input"])
            with c2:
                st.markdown("**Output**")
                _show(e["output"])