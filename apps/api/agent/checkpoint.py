"""LangGraph checkpoints (chat history + runs paused for approval), stored in Postgres and encrypted.

Message history contains portfolio details, so every checkpoint blob is sealed with the same
AES-256-GCM data keys as the rest of the app (FOXHOOD_DATA_KEYS), under its own AAD label.
No second key to manage, and key rotation works the same way."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from sqlalchemy.engine import make_url

from app.settings import settings
from db.crypto import get_cipher

CIPHER_NAME = "foxhood-gcm"
AAD = "langgraph.checkpoint"


class _DataKeyCipher:
    """LangGraph's CipherProtocol, backed by our versioned AES-GCM Cipher."""

    def encrypt(self, plaintext: bytes) -> tuple[str, bytes]:
        return CIPHER_NAME, get_cipher().encrypt(plaintext, AAD).encode()

    def decrypt(self, ciphername: str, ciphertext: bytes) -> bytes:
        if ciphername != CIPHER_NAME:
            raise ValueError(f"Unsupported checkpoint cipher {ciphername!r}")
        return get_cipher().decrypt(ciphertext.decode(), AAD)


SERDE = EncryptedSerializer(_DataKeyCipher())
_setup_done = False
_setup_lock = asyncio.Lock()
SETUP_LOCK_KEY = 7_412_903_001   # any fixed number; Postgres advisory lock shared by every API instance


def _conninfo() -> str:
    """psycopg wants plain postgresql://, not SQLAlchemy's postgresql+psycopg://."""
    url = make_url(settings.database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """One connection per agent run. Creates LangGraph's tables on first use (idempotent)."""
    global _setup_done
    async with AsyncPostgresSaver.from_conn_string(_conninfo(), serde=SERDE) as saver:
        if not _setup_done:
            # Two runs starting at once (here, or on another server instance) would both try to create
            # the tables and one would crash. The lock makes them take turns; the second finds them done.
            async with _setup_lock:
                if not _setup_done:
                    async with saver.conn.cursor() as cur:
                        await cur.execute("SELECT pg_advisory_lock(%s)", (SETUP_LOCK_KEY,))
                        try:
                            await saver.setup()
                        finally:
                            await cur.execute("SELECT pg_advisory_unlock(%s)", (SETUP_LOCK_KEY,))
                    _setup_done = True
        yield saver


async def delete_thread_checkpoints(thread_id: str) -> None:
    async with open_checkpointer() as saver:
        await saver.adelete_thread(thread_id)


async def purge_user_checkpoints(user_id) -> None:
    """Erase every checkpoint for a user (account deletion). Thread ids all start with '<user_id>:'."""
    async with open_checkpointer() as saver, saver.conn.cursor() as cur:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            await cur.execute(f"DELETE FROM {table} WHERE thread_id LIKE %s", (f"{user_id}:%",))
