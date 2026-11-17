"""Chat, approvals, briefs, threads and usage. Runs stream back as server-sent events (see app/runs.py):
token, tool_start, tool_end, denied, approval_required, done / error (and brief, for briefs)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from agent.briefs import get_or_create_brief
from agent.runner import arun_agent, check_thread, delete_thread, get_thread_state
from agent.tracing import content_to_text
from app.deps import CurrentUserDep, RepoDep, SessionDep
from app.runs import is_busy, single_event_response, start_run
from app.schemas import (
    ApproveIn,
    BriefOut,
    ChatIn,
    ChatMessageOut,
    ThreadDetailOut,
    ThreadOut,
    ThreadUpdate,
    UsageOut,
)
from app.settings import settings
from core.market_clock import current_brief_slot
from db.repo import AdminRepo, UserRepo

router = APIRouter()


def agent_options() -> dict[str, Any]:
    """Extra arguments for every agent run. Tests override this to use a scripted model and no MCP."""
    return {}


AgentOptions = Annotated[dict, Depends(agent_options)]


async def _check_budget(repo: UserRepo, session: SessionDep) -> None:
    if await AdminRepo(session).global_spent_today() >= settings.daily_cap_total_usd:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Foxhood has hit its shared daily AI budget. It resets at midnight ET.")
    if await repo.spent_today() >= settings.daily_cap_user_usd:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "You've reached today's AI limit. It resets at midnight ET.")


# ---- chat ----
@router.post("/chat")
async def chat(body: ChatIn, user: CurrentUserDep, repo: RepoDep, session: SessionDep,
               options: AgentOptions) -> StreamingResponse:
    if body.thread_id:
        check_thread(user.id, body.thread_id)
        await repo.get_thread(body.thread_id)     # 404 before streaming if it isn't theirs
    await _check_budget(repo, session)
    return start_run(user.id, lambda emit: arun_agent(
        user.id, body.message, thread_id=body.thread_id, on_event=emit, **options))


@router.post("/threads/{thread_id}/approve")
async def approve(thread_id: str, body: ApproveIn, user: CurrentUserDep, repo: RepoDep,
                  session: SessionDep, options: AgentOptions) -> StreamingResponse:
    check_thread(user.id, thread_id)
    await repo.get_thread(thread_id)
    if is_busy(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a request running. Wait for it to finish.")
    pending = (await get_thread_state(user.id, thread_id))["pending"]
    if not pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for approval in this conversation.")
    unknown = set(body.decisions) - {p["id"] for p in pending}
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Decision for an action that isn't pending.")
    await _check_budget(repo, session)
    resume = {"decisions": {k: v.model_dump() for k, v in body.decisions.items()}, "by": "user"}
    return start_run(user.id, lambda emit: arun_agent(
        user.id, resume=resume, thread_id=thread_id, parent_run_id=body.run_id, on_event=emit, **options))


# ---- threads ----
def _messages_out(messages: list) -> list[ChatMessageOut]:
    out: list[ChatMessageOut] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append(ChatMessageOut(role="user", text=content_to_text(m.content)))
        elif isinstance(m, AIMessage):
            text = content_to_text(m.content).strip()
            tools = [tc["name"] for tc in m.tool_calls or []]
            if text or tools:
                out.append(ChatMessageOut(role="assistant", text=text, tools=tools))
    return out


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(repo: RepoDep, archived: bool = False) -> list[ThreadOut]:
    threads = await repo.list_threads(include_archived=archived)
    return [ThreadOut.model_validate(t) for t in threads if t.archived == archived]


@router.get("/threads/{thread_id}", response_model=ThreadDetailOut)
async def get_thread(thread_id: str, user: CurrentUserDep, repo: RepoDep) -> ThreadDetailOut:
    thread = await repo.get_thread(thread_id)
    state = await get_thread_state(user.id, thread_id)
    return ThreadDetailOut(thread=ThreadOut.model_validate(thread), messages=_messages_out(state["messages"]),
                           pending=state["pending"])


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(thread_id: str, body: ThreadUpdate, repo: RepoDep) -> ThreadOut:
    thread = await repo.get_thread(thread_id)
    if body.title is not None:
        thread = await repo.rename_thread(thread_id, body.title)
    if body.archived is not None:
        thread = await repo.archive_thread(thread_id, body.archived)
    return ThreadOut.model_validate(thread)


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_thread(thread_id: str, user: CurrentUserDep) -> Response:
    if is_busy(user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait for the current request to finish first.")
    await delete_thread(user.id, thread_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- briefs ----
@router.post("/briefs/today")
async def todays_brief(user: CurrentUserDep, repo: RepoDep, session: SessionDep,
                       options: AgentOptions) -> StreamingResponse:
    """The brief for the current slot: instant if it's saved, otherwise generated (streamed)."""
    slot = current_brief_slot()
    saved = await repo.get_brief(slot.brief_date, slot.session)
    if saved:
        return single_event_response({"type": "brief", "cached": True,
                                      **BriefOut.model_validate(saved).model_dump(mode="json")})
    await _check_budget(repo, session)

    async def job(emit):
        brief = await get_or_create_brief(user.id, slot, on_event=emit, **options)
        emit({"type": "brief", "cached": False, **BriefOut.model_validate(brief).model_dump(mode="json")})

    return start_run(user.id, job)


@router.get("/briefs", response_model=list[BriefOut])
async def list_briefs(repo: RepoDep, limit: int = 30) -> list[BriefOut]:
    return [BriefOut.model_validate(b) for b in await repo.list_briefs(limit=min(max(limit, 1), 100))]


# ---- usage ----
@router.get("/usage/today", response_model=UsageOut)
async def usage_today(repo: RepoDep) -> UsageOut:
    spent, cap = await repo.spent_today(), settings.daily_cap_user_usd
    return UsageOut(spent_usd=float(spent), cap_usd=float(cap), remaining_usd=float(max(cap - spent, 0)))