"""Admin command line. Run from apps/api:

    uv run python -m app.cli invite friend@gmail.com
    uv run python -m app.cli revoke friend@gmail.com
    uv run python -m app.cli list-invites
    uv run python -m app.cli list-users
    uv run python -m app.cli seed-demo you@gmail.com --persona aggressive [--replace]
"""
from __future__ import annotations

import argparse
import asyncio

from db.repo import AdminRepo, UserRepo
from db.session import SessionLocal
from storage.seed_demo import DEMO_USERS  # the POC's synthetic personas (moves into db/ in M2)

PERSONAS = {"aggressive": 0, "balanced": 1, "income": 2}


async def invite(email: str) -> None:
    async with SessionLocal() as s:
        inv = await AdminRepo(s).invite(email, invited_by="cli")
        print(f"Invited {inv.email}")


async def revoke(email: str) -> None:
    async with SessionLocal() as s:
        print("Revoked." if await AdminRepo(s).revoke(email) else "No invite found for that email.")


async def list_invites() -> None:
    async with SessionLocal() as s:
        for inv in await AdminRepo(s).list_invites():
            status = "revoked" if inv.revoked_at else "accepted" if inv.accepted_at else "pending"
            print(f"{inv.email:40} {status:9} invited {inv.created_at:%Y-%m-%d}")


async def list_users() -> None:
    async with SessionLocal() as s:
        for u in await AdminRepo(s).list_users():
            last = f"{u['last_login_at']:%Y-%m-%d}" if u["last_login_at"] else "never"
            print(f"{u['email']:40} holdings={u['holdings']:<3} watchlist={u['watchlist']:<3} "
                  f"memories={u['memories']:<3} last login: {last}")


async def seed_demo(email: str, persona: str, replace: bool) -> None:
    demo = DEMO_USERS[PERSONAS[persona]]
    async with SessionLocal() as s:
        user = await AdminRepo(s).get_or_create_user(email)
        repo = UserRepo(s, user.id)
        if replace:
            for h in await repo.list_holdings():
                await repo.delete_holding(h.id)
            for w in await repo.list_watchlist():
                await repo.delete_watch_item(w.id)
            for m in await repo.list_memories():
                await repo.delete_memory(m.id)
        await repo.update_profile(persona=f"{demo['persona']} (demo data)", risk_tolerance=demo["risk_tolerance"],
                                  horizon=demo["horizon"], interests=demo["interests"])
        for h in demo["holdings"]:
            await repo.add_holding(source="seed", **h)
        for ticker, note in demo["watchlist"]:
            await repo.add_to_watchlist(ticker, note)
        for m in demo["memories"]:
            await repo.add_memory(m["kind"], m["content"], m["tags"], source_run_id="seed")
        print(f"Seeded {email} with the '{persona}' demo portfolio: {len(demo['holdings'])} lots, "
              f"{len(demo['watchlist'])} watchlist tickers, {len(demo['memories'])} memories (all synthetic).")


def main() -> None:
    p = argparse.ArgumentParser(prog="app.cli", description="Foxhood admin commands")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("invite").add_argument("email")
    sub.add_parser("revoke").add_argument("email")
    sub.add_parser("list-invites")
    sub.add_parser("list-users")
    sd = sub.add_parser("seed-demo")
    sd.add_argument("email")
    sd.add_argument("--persona", choices=sorted(PERSONAS), default="aggressive")
    sd.add_argument("--replace", action="store_true", help="delete existing holdings/watchlist/memories first")
    a = p.parse_args()

    if a.cmd == "invite":
        asyncio.run(invite(a.email))
    elif a.cmd == "revoke":
        asyncio.run(revoke(a.email))
    elif a.cmd == "list-invites":
        asyncio.run(list_invites())
    elif a.cmd == "list-users":
        asyncio.run(list_users())
    elif a.cmd == "seed-demo":
        asyncio.run(seed_demo(a.email, a.persona, a.replace))


if __name__ == "__main__":
    main()