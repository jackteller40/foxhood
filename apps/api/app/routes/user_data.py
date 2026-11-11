"""User data endpoints. Every handler receives a UserRepo bound to the verified caller, so there is
no way to address another user's data from here; someone else's id simply returns 404."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.deps import CurrentUserDep, RepoDep
from app.schemas import (
    DeleteAccountIn,
    HoldingIn,
    HoldingOut,
    MemoryIn,
    MemoryOut,
    MeOut,
    ProfileOut,
    ProfileUpdate,
    WatchIn,
    WatchOut,
)

router = APIRouter()


# ---- account ----
@router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep, repo: RepoDep) -> MeOut:
    profile = await repo.get_profile()
    if not profile["name"] and user.name:  # first sign-in: start from the Google display name
        profile = await repo.update_profile(name=user.name)
    return MeOut(id=user.id, email=user.email, name=profile["name"], profile=ProfileOut(**profile))


@router.get("/me/profile", response_model=ProfileOut)
async def get_profile(repo: RepoDep) -> ProfileOut:
    return ProfileOut(**await repo.get_profile())


@router.patch("/me/profile", response_model=ProfileOut)
async def update_profile(body: ProfileUpdate, repo: RepoDep) -> ProfileOut:
    return ProfileOut(**await repo.update_profile(**body.model_dump(exclude_unset=True)))


@router.get("/me/export")
async def export_my_data(repo: RepoDep) -> JSONResponse:
    return JSONResponse(await repo.export(),
                        headers={"Content-Disposition": 'attachment; filename="foxhood-export.json"'})


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(body: DeleteAccountIn, repo: RepoDep) -> None:
    await repo.delete_account()


# ---- holdings ----
@router.get("/holdings", response_model=list[HoldingOut])
async def list_holdings(repo: RepoDep) -> list[HoldingOut]:
    return [HoldingOut.model_validate(h) for h in await repo.list_holdings()]


@router.post("/holdings", response_model=HoldingOut, status_code=status.HTTP_201_CREATED)
async def add_holding(body: HoldingIn, repo: RepoDep) -> HoldingOut:
    h = await repo.add_holding(body.ticker, body.purchase_date, shares=body.shares, amount=body.amount)
    return HoldingOut.model_validate(h)


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(holding_id: uuid.UUID, repo: RepoDep) -> None:
    await repo.delete_holding(holding_id)


# ---- watchlist ----
@router.get("/watchlist", response_model=list[WatchOut])
async def list_watchlist(repo: RepoDep) -> list[WatchOut]:
    return [WatchOut.model_validate(w) for w in await repo.list_watchlist()]


@router.post("/watchlist", response_model=WatchOut)
async def add_to_watchlist(body: WatchIn, repo: RepoDep, response: Response) -> WatchOut:
    item, created = await repo.add_to_watchlist(body.ticker, body.note)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return WatchOut.model_validate(item)


@router.delete("/watchlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_item(item_id: uuid.UUID, repo: RepoDep) -> None:
    await repo.delete_watch_item(item_id)


# ---- memories ----
@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(repo: RepoDep, kind: Literal["preference", "fact", "brief_takeaway"] | None = None,
                        ) -> list[MemoryOut]:
    return [MemoryOut.model_validate(m) for m in await repo.list_memories(kind=kind)]


@router.post("/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def add_memory(body: MemoryIn, repo: RepoDep) -> MemoryOut:
    return MemoryOut.model_validate(await repo.add_memory(body.kind, body.content, body.tags))


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, repo: RepoDep) -> None:
    await repo.delete_memory(memory_id)