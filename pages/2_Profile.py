import streamlit as st

st.set_page_config(page_title="Profile", page_icon="👤", layout="wide")

from storage import db
from ui.common import flash, fmt_time, open_trace, sidebar

user = sidebar()
uid = user["id"]
st.title("Profile")
flash()

st.subheader("About you")
with st.form("profile"):
    levels = ["low", "medium", "high"]
    risk = st.selectbox("Risk tolerance", levels, index=levels.index(user["risk_tolerance"]))
    horizon = st.text_input("Investment horizon", user.get("horizon") or "")
    interests = st.text_input("Interests (comma-separated)", ", ".join(user["interests"]))
    if st.form_submit_button("Save profile", type="primary"):
        db.update_user(uid, risk_tolerance=risk, horizon=horizon.strip() or None,
                       interests=[i.strip() for i in interests.split(",") if i.strip()])
        flash("Profile saved. Regenerate the brief to see it reflected.")
        st.rerun()

left, right = st.columns(2)

with left:
    st.subheader("Watchlist")
    for w in db.list_watchlist(uid):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{w['ticker']}**" + (f": {w['note']}" if w["note"] else ""))
        if c2.button("Remove", key=f"wl-{w['ticker']}"):
            db.remove_from_watchlist(uid, w["ticker"])
            flash(f"Removed {w['ticker']} from your watchlist.")
            st.rerun()
    with st.form("add_watch", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        t = c1.text_input("Ticker").strip().upper()
        note = c2.text_input("Note (optional)")
        if st.form_submit_button("Add to watchlist") and t:
            db.add_to_watchlist(uid, t, note.strip() or None)
            flash(f"Added {t} to your watchlist.")
            st.rerun()

with right:
    st.subheader("What the agent remembers")
    st.caption("The agent recalls these when relevant. It can only save new ones with your approval.")
    for m in db.list_memories(uid, limit=100):
        with st.container(border=True):
            st.markdown(f"**{m['kind']}**: {m['content']}")
            src = m["source_run_id"]
            st.caption(f"Tags: {', '.join(m['tags']) or '-'} · saved {fmt_time(m['created_at'])}"
                       + (f" · from run `{src[:8]}`" if src and src != "seed" else " · seed data" if src == "seed" else ""))
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Delete", key=f"mem-del-{m['id']}"):
                db.delete_memory(uid, m["id"])
                flash("Memory deleted.")
                st.rerun()
            if src and src != "seed" and c2.button("View trace", key=f"mem-tr-{m['id']}"):
                open_trace(src)
    with st.form("add_memory", clear_on_submit=True):
        content = st.text_input("Add a memory yourself")
        kind = st.selectbox("Kind", ["preference", "fact"])
        if st.form_submit_button("Save memory") and content.strip():
            db.add_memory(uid, kind, content.strip(), source_run_id=None)
            flash("Memory saved.")
            st.rerun()