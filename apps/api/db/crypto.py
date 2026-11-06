"""Field encryption: AES-256-GCM with versioned keys and per-value associated data (AAD).

Stored format (fits a TEXT column):  "<key version>.<base64url(nonce || ciphertext+tag)>"

AAD binds each value to exactly where it belongs: table, column, owner and row
(e.g. "holdings.payload:<user_id>:<row_id>"). A value copied into another user's row, another
row, or another table fails to decrypt instead of showing up there. GCM also detects any tampering.

Keys come from FOXHOOD_DATA_KEYS = "v1:<base64 32 bytes>,v2:<...>". New values use the active key
(FOXHOOD_ACTIVE_KEY, default: the last one listed); old versions stay readable, so keys can rotate."""
from __future__ import annotations

import base64
import binascii
import json
import os
from functools import lru_cache
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class DecryptionError(Exception):
    """The value is corrupt, tampered with, in the wrong place, or under an unknown key."""


def field_aad(table: str, column: str, user_id: UUID | str | None, row_id: UUID | str) -> str:
    return f"{table}.{column}:{user_id or 'none'}:{row_id}"


def _parse_keys(spec: str) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        version, sep, b64 = part.partition(":")
        if not sep or not version or "." in version:
            raise ValueError(f"Bad key entry {part[:6]!r}...: expected 'version:base64key'")
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise ValueError(f"Key {version!r} must be 32 bytes (AES-256), got {len(key)}")
        keys[version] = key
    return keys


class Cipher:
    def __init__(self, keys: dict[str, bytes], active: str):
        if active not in keys:
            raise ValueError(f"Active key {active!r} is not among the configured keys")
        self._aes = {version: AESGCM(key) for version, key in keys.items()}
        self.active = active

    @classmethod
    def from_spec(cls, spec: str, active: str | None = None) -> Cipher:
        keys = _parse_keys(spec)
        if not keys:
            raise RuntimeError("No data keys configured. Set FOXHOOD_DATA_KEYS (see .env.example).")
        return cls(keys, active or list(keys)[-1])

    @classmethod
    def from_env(cls) -> Cipher:
        return cls.from_spec(os.getenv("FOXHOOD_DATA_KEYS", ""), os.getenv("FOXHOOD_ACTIVE_KEY") or None)

    def encrypt(self, plaintext: bytes, aad: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aes[self.active].encrypt(nonce, plaintext, aad.encode())
        return f"{self.active}.{base64.urlsafe_b64encode(nonce + sealed).decode()}"

    def decrypt(self, token: str, aad: str) -> bytes:
        version, sep, body = token.partition(".")
        aes = self._aes.get(version)
        if not sep or aes is None:
            raise DecryptionError(f"Unknown key version {version!r}")
        try:
            raw = base64.urlsafe_b64decode(body)
            return aes.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad.encode())
        except (InvalidTag, binascii.Error, ValueError):
            raise DecryptionError("Value failed authentication (tampered, corrupt, or wrong place)") from None

    def encrypt_json(self, value: Any, aad: str) -> str:
        return self.encrypt(json.dumps(value, separators=(",", ":"), default=str).encode(), aad)

    def decrypt_json(self, token: str, aad: str) -> Any:
        return json.loads(self.decrypt(token, aad))

    def needs_rotation(self, token: str) -> bool:
        return not token.startswith(f"{self.active}.")


@lru_cache(maxsize=1)
def get_cipher() -> Cipher:
    import core.config  # noqa: F401  (loads apps/api/.env)
    return Cipher.from_env()