import uuid

from sqlalchemy import select, text

from db.crypto import field_aad, get_cipher
from db.models import Holding, User
from db.session import SessionLocal

EXPECTED = {"users", "invites", "holdings", "watchlist", "memories", "briefs", "trace_events", "usage"}


async def test_migration_created_tables():
    async with SessionLocal() as s:
        rows = await s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        assert EXPECTED <= {r[0] for r in rows}


async def test_holding_stored_encrypted_and_deleted_with_user():
    cipher = get_cipher()
    async with SessionLocal() as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.com")
        s.add(user)
        await s.flush()

        hid = uuid.uuid4()
        aad = field_aad("holdings", "payload", user.id, hid)
        payload = {"ticker": "NVDA", "purchase_date": "2024-06-03", "shares": 10, "amount": None}
        s.add(Holding(id=hid, user_id=user.id, payload_enc=cipher.encrypt_json(payload, aad)))
        await s.commit()

        raw = (await s.execute(text("SELECT payload_enc FROM holdings WHERE id = :id"), {"id": hid})).scalar_one()
        assert "NVDA" not in raw                      # what the database actually holds
        assert cipher.decrypt_json(raw, aad) == payload

        await s.delete(user)
        await s.commit()
        assert (await s.execute(select(Holding).where(Holding.id == hid))).scalar_one_or_none() is None