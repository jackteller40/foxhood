import streamlit as st

st.set_page_config(page_title="Daily brief", page_icon="📈", layout="wide")

from datetime import datetime

from agent.briefs import get_or_create_brief
from core.market_clock import current_brief_slot, slot_for
from datasources.market import ET
from storage import db
from ui.common import fmt_time, run_footer, sidebar

user = sidebar()
uid = user["id"]
LABELS = {"premarket": "Pre-market brief", "close": "Post-close recap"}
SESSIONS = ["premarket", "close"]

hour = datetime.now(ET).hour
greeting = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
st.title(f"Good {greeting}, {user['name'].split()[0]}")

now_slot = current_brief_slot()
choice = st.radio("Brief", SESSIONS, index=SESSIONS.index(now_slot.session), format_func=LABELS.get,
                  horizontal=True, label_visibility="collapsed")
slot = slot_for(choice)
st.caption(f"**{LABELS[slot.session]}** for {slot.brief_date:%A, %B %d, %Y} ({slot.reason})")

key = (uid, slot.brief_date.isoformat(), slot.session)
failed = st.session_state.setdefault("brief_failed", set())


def generate(force: bool = False):
    with st.status(f"Writing your {LABELS[slot.session].lower()}... (about 30 seconds)", expanded=False) as s:
        try:
            b = get_or_create_brief(uid, slot, force=force)
            s.update(label="Brief ready", state="complete")
            return b
        except Exception as e:
            failed.add(key)
            s.update(label="Brief failed. See the error below and the Trace page.", state="error")
            st.error(f"{type(e).__name__}: {e}")
            return None


brief = db.get_brief(uid, slot.brief_date, slot.session)
if brief is None and choice == now_slot.session and key not in failed:
    brief = generate()  # the current brief is generated automatically when the app opens

if brief:
    with st.container(border=True):
        st.markdown(brief["content_md"])
    st.caption(f"Generated {fmt_time(brief['created_at'])}")
    if brief.get("run_id"):
        run_footer(brief["run_id"], key="brief-trace")
    if st.button("Regenerate", icon="🔄"):
        failed.discard(key)
        if generate(force=True):
            st.rerun()
else:
    st.info(f"No {LABELS[slot.session].lower()} yet for this date.")
    if st.button(f"Generate {LABELS[slot.session].lower()}", type="primary"):
        failed.discard(key)
        if generate():
            st.rerun()