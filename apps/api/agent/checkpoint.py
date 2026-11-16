"""LangGraph checkpoints (chat history + runs paused for approval), stored in Postgres and encrypted.

Message history contains portfolio details, so every checkpoint blob is sealed with the same
AES-256-GCM data keys as the rest of the app (FOXHOOD_DATA_KEYS), under its own AAD label.
No second key to manage, and key rotation works the same way."""
from __future__ import annotations

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
            await saver.setup()
            _setup_done = True
        yield saver