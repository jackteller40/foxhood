"""Chat threads: titled, listed per user, private, and deleting one really erases its messages."""
import pytest
from sqlalchemy import text

from agent.runner import arun_agent, delete_thread, get_thread_state
from db.repo import AdminRepo, NotFound, UserRepo, thread_title
from tests.test_agent import ScriptedModel, say


async def _chat(repo, question: str, thread_id: str | None = None):
    model = ScriptedModel(responses=[say("Noted.")])
    return await arun_agent(repo.user_id, question, thread_id=thread_id, model=model, use_mcp=False)


async def _checkpoint_rows(session, pattern: str) -> int:
    q = ("SELECT (SELECT count(*) FROM checkpoints WHERE thread_id LIKE :p) + "
         "(SELECT count(*) FROM checkpoint_blobs WHERE thread_id LIKE :p) + "
         "(SELECT count(*) FROM checkpoint_writes WHERE thread_id LIKE :p)")
    return (await session.execute(text(q), {"p": pattern})).scalar_one()


def test_thread_title():
    assert thread_title("  How is   my\nportfolio? ") == "How is my portfolio?"
    long = thread_title("What does the latest CPI print mean for my bond ETFs and my tech-heavy positions?")
    assert long.endswith("…") and len(long) <= 61 and not long[:-1].endswith(" ")
    assert thread_title("") == "New chat"


async def test_threads_listed_titled_and_private(make_user, session):
    alice, bob = await make_user(), await make_user()
    first = await _chat(alice, "How exposed am I to rate cuts?")
    second = await _chat(alice, "Anything new on NVDA?")
    await _chat(alice, "Follow-up question", thread_id=first.thread_id)   # same thread, bumped to the top

    threads = await alice.list_threads()
    assert [t.id for t in threads] == [first.thread_id, second.thread_id]
    assert threads[0].title == "How exposed am I to rate cuts?"           # title stays the first question
    assert await bob.list_threads() == []
    with pytest.raises(NotFound):
        await bob.get_thread(first.thread_id)

    raw = (await session.execute(text("SELECT title_enc FROM chat_threads WHERE id = :t"),
                                 {"t": first.thread_id})).scalar_one()
    assert "rate cuts" not in raw

    await alice.rename_thread(first.thread_id, "Rates")
    await alice.archive_thread(second.thread_id)
    assert [t.title for t in await alice.list_threads()] == ["Rates"]
    assert len(await alice.list_threads(include_archived=True)) == 2


async def test_delete_thread_erases_its_messages(make_user, session):
    alice = await make_user()
    r = await _chat(alice, "Delete me later")
    assert await _checkpoint_rows(session, r.thread_id) > 0
    await delete_thread(alice.user_id, r.thread_id)
    assert await _checkpoint_rows(session, r.thread_id) == 0
    assert await alice.list_threads() == []
    assert (await get_thread_state(alice.user_id, r.thread_id))["messages"] == []


async def test_cannot_delete_someone_elses_thread(make_user):
    alice, bob = await make_user(), await make_user()
    r = await _chat(alice, "Mine")
    with pytest.raises(NotFound):
        await delete_thread(bob.user_id, r.thread_id)
    assert len(await alice.list_threads()) == 1


async def test_account_deletion_erases_checkpoints(client, invited_user, session):
    headers, email, _sub = await invited_user()
    assert (await client.get("/me", headers=headers)).status_code == 200   # first sign-in creates the user
    user = await AdminRepo(session).find_user(email)
    await _chat(UserRepo(session, user.id), "Something private")
    assert await _checkpoint_rows(session, f"{user.id}:%") > 0

    resp = await client.request("DELETE", "/me", json={"confirm": "DELETE"}, headers=headers)
    assert resp.status_code == 204
    assert await _checkpoint_rows(session, f"{user.id}:%") == 0