import streamlit as st

st.set_page_config(page_title="Trace", page_icon="🔍", layout="wide")

from storage import db
from ui.common import STATUS_ICON, fmt_time, render_trace, sidebar

user = sidebar()
st.title("Agent traces")
st.caption("Every run's linked events: the main agent, LLM calls, tools, MCP, skills, memory, the news "
           "subagent, and permission decisions. The same run ids appear in LangSmith.")

runs = db.list_runs(user_id=user["id"], limit=50)
if not runs:
    st.info("No runs yet for this user. Open the brief or ask a question first.")
    st.stop()

by_id = {r["root_run_id"]: r for r in runs}
ids = list(by_id)
wanted = st.session_state.get("trace_run_id")


def label(rid: str) -> str:
    r = by_id[rid]
    status = r["run_status"] or "?"
    extra = (f" · {r['denials']} denied" if r["denials"] else "") + (f" · {r['errors']} errors" if r["errors"] else "")
    return f"{fmt_time(r['run_started'])} · {r['run_name']} · {STATUS_ICON.get(status, '')} {status} · {r['events']} events{extra}"


selected = st.selectbox("Run", ids, index=ids.index(wanted) if wanted in ids else 0, format_func=label)
st.session_state["trace_run_id"] = selected
run = by_id[selected]

root = next((e for e in db.get_run_events(selected) if e["event_type"] == "run"), None)
if root and isinstance(root["input"], dict):
    q = root["input"].get("question")
    if q:
        st.markdown(f"**Request:** {q}")
    elif root["input"].get("resume"):
        st.markdown("**Resumed after approval decision:**")
        st.json(root["input"]["resume"], expanded=False)

nav = st.columns(3)
if run["resumes_run_id"] and run["resumes_run_id"] in by_id and nav[0].button("Previous run (paused)", icon="⬅️"):
    st.session_state["trace_run_id"] = run["resumes_run_id"]
    st.rerun()
child = next((r for r in runs if r["resumes_run_id"] == selected), None)
if child and nav[1].button("Resumed in", icon="➡️"):
    st.session_state["trace_run_id"] = child["root_run_id"]
    st.rerun()
st.caption(f"Run id `{selected}`. Search for it in LangSmith to see the same run there.")

render_trace(selected)