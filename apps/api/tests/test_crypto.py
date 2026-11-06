import base64
import uuid

import pytest

from db.crypto import Cipher, DecryptionError, field_aad

K1 = base64.b64encode(b"\x01" * 32).decode()
K2 = base64.b64encode(b"\x02" * 32).decode()
ALICE, BOB, ROW = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
AAD = field_aad("holdings", "payload", ALICE, ROW)
PAYLOAD = {"ticker": "NVDA", "shares": 10, "purchase_date": "2024-06-03"}


def test_roundtrip():
    c = Cipher.from_spec(f"v1:{K1}")
    assert c.decrypt_json(c.encrypt_json(PAYLOAD, AAD), AAD) == PAYLOAD


def test_ciphertext_hides_plaintext_and_is_randomized():
    c = Cipher.from_spec(f"v1:{K1}")
    a, b = c.encrypt_json(PAYLOAD, AAD), c.encrypt_json(PAYLOAD, AAD)
    assert "NVDA" not in a and a != b  # random nonce: same input never encrypts the same way twice


def test_tampering_detected():
    c = Cipher.from_spec(f"v1:{K1}")
    token = c.encrypt_json(PAYLOAD, AAD)
    i = len(token) // 2
    tampered = token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1:]
    with pytest.raises(DecryptionError):
        c.decrypt_json(tampered, AAD)


def test_copied_to_another_user_fails():
    c = Cipher.from_spec(f"v1:{K1}")
    token = c.encrypt_json(PAYLOAD, AAD)
    with pytest.raises(DecryptionError):
        c.decrypt_json(token, field_aad("holdings", "payload", BOB, ROW))


def test_copied_to_another_table_fails():
    c = Cipher.from_spec(f"v1:{K1}")
    token = c.encrypt_json(PAYLOAD, AAD)
    with pytest.raises(DecryptionError):
        c.decrypt_json(token, field_aad("watchlist", "payload", ALICE, ROW))


def test_key_rotation():
    old = Cipher.from_spec(f"v1:{K1}")
    token_v1 = old.encrypt_json(PAYLOAD, AAD)
    new = Cipher.from_spec(f"v1:{K1},v2:{K2}")  # v2 is active (last listed)
    assert new.decrypt_json(token_v1, AAD) == PAYLOAD  # old data still readable
    assert new.needs_rotation(token_v1)
    token_v2 = new.encrypt_json(PAYLOAD, AAD)
    assert token_v2.startswith("v2.") and not new.needs_rotation(token_v2)


def test_unknown_key_version():
    token_v1 = Cipher.from_spec(f"v1:{K1}").encrypt_json(PAYLOAD, AAD)
    with pytest.raises(DecryptionError):
        Cipher.from_spec(f"v2:{K2}").decrypt_json(token_v1, AAD)


def test_bad_key_rejected():
    with pytest.raises(ValueError):
        Cipher.from_spec("v1:" + base64.b64encode(b"short").decode())