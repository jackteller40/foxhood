import streamlit as st

st.set_page_config(page_title="Ask", page_icon="💬", layout="wide")

import uuid

from langchain_core.messages import AIMessage, HumanMessage

from agent.runner import get_thread_state, run_agent
from agent.tracing import content_to_text
from ui.common import run_footer, sidebar

user = sidebar()
uid = user["id"]

threads = st.session_state.setdefault("chat_threads", {})
thread_id = threads.setdefault(uid, f"chat-u{uid}")         # default thread survives restarts
turn_runs = st.session_state.setdefault("turn_runs", {})    # final AI message id -> run_id
paused = st.session_state.setdefault("paused_runs", {})     # thread_id -> paused run_id

head, btn = st.columns([5, 1])
head.title("Ask")
if btn.button("New chat", icon="🧹"):
    threads[uid] = f"chat-u{uid}-{uuid.uuid4().hex[:6]}"
    st.rerun()
st.caption("Ask about your portfolio, a holding, or the market. Changes to your watchlist, holdings "
           "or saved memories need your approval. Trades are never placed.")


def handle_result(r) -> None:
    if r.status == "paused":
        paused[thread_id] = r.run_id
        return
    paused.pop(thread_id, None)
    final = next((m for m in reversed(r.messages) if isinstance(m, AIMessage) and not m.tool_calls), None)
    if final is not None and final.id:
        turn_runs[final.id] = r.run_id


state = get_thread_state(thread_id)
for m in state["messages"]:
    if isinstance(m, HumanMessage):
        with st.chat_message("user"):
            st.markdown(content_to_text(m.content))
    elif isinstance(m, AIMessage) and not m.tool_calls:
        text = content_to_text(m.content).strip()
        if text:
            with st.chat_message("assistant"):
                st.markdown(text)
                if rid := turn_runs.get(m.id):
                    run_footer(rid, key=f"footer-{m.id}")

pending = state["pending"]
if pending:
    with st.chat_message("assistant", avatar="🛡️"):
        st.markdown("**Approval needed.** The agent wants to make these changes:")
        choices = {}
        for req in pending:
            with st.container(border=True):
                st.markdown(f"**{req['tool']}**: {req['reason']}")
                st.json(req["args"])
                choices[req["id"]] = st.radio("Decision", ["Approve", "Reject"], key=f"dec-{req['id']}",
                                              horizontal=True)
        if st.button("Submit decision", type="primary"):
            decisions = {rid: {"approved": c == "Approve"} for rid, c in choices.items()}
            with st.status("Continuing...", expanded=False):
                r = run_agent(uid, resume={"decisions": decisions, "by": user["name"]},
                              thread_id=thread_id, parent_run_id=paused.get(thread_id))
            handle_result(r)
            st.rerun()

prompt = st.chat_input("Ask about your portfolio, a stock, or the market...", disabled=bool(pending))
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.status("Researching... (portfolio tools, news analyst, macro data)", expanded=False) as status:
            try:
                r = run_agent(uid, prompt, thread_id=thread_id)
                status.update(label="Done", state="complete")
            except Exception as e:
                status.update(label="Run failed. See the Trace page.", state="error")
                st.error(f"{type(e).__name__}: {e}")
                st.stop()
    handle_result(r)
    st.rerun()