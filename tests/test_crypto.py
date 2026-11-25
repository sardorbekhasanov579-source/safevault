import os

import pytest

from safevault_client import crypto as C


def test_file_roundtrip_sizes():
    mk = C.new_master_key()
    for n in (0, 1, 1000, C.CHUNK - 1, C.CHUNK, C.CHUNK + 1, 3 * C.CHUNK, 3 * C.CHUNK + 17):
        data = os.urandom(n)
        assert C.decrypt_file(mk, C.encrypt_file(mk, data)) == data, n


def test_wrong_key_fails():
    blob = C.encrypt_file(C.new_master_key(), b"salom")
    with pytest.raises(C.CryptoError):
        C.decrypt_file(C.new_master_key(), blob)


def test_tamper_detected():
    mk = C.new_master_key()
    blob = bytearray(C.encrypt_file(mk, os.urandom(5000)))
    blob[-5] ^= 1
    with pytest.raises(C.CryptoError):
        C.decrypt_file(mk, bytes(blob))


def test_truncation_at_chunk_boundary_detected():
    mk = C.new_master_key()
    blob = C.encrypt_file(mk, os.urandom(3 * C.CHUNK))
    header = len(blob) - 3 * (C.CHUNK + 16)
    with pytest.raises(C.CryptoError):
        C.decrypt_file(mk, blob[:header + 2 * (C.CHUNK + 16)])  # oxirgi bo'lak olib tashlangan


def test_chunk_reorder_detected():
    mk = C.new_master_key()
    blob = C.encrypt_file(mk, os.urandom(3 * C.CHUNK))
    header = len(blob) - 3 * (C.CHUNK + 16)
    step = C.CHUNK + 16
    c0, c1, c2 = (blob[header + i * step: header + (i + 1) * step] for i in range(3))
    with pytest.raises(C.CryptoError):
        C.decrypt_file(mk, blob[:header] + c1 + c0 + c2)


def test_password_and_recovery_wrap():
    mk = C.new_master_key()
    salt = C.new_salt()
    kek, auth = C.password_keys("Parol-123", salt)
    assert kek != auth and len(kek) == len(auth) == 32
    assert C.password_keys("Parol-123", salt) == (kek, auth)
    assert C.password_keys("parol-123", salt)[0] != kek

    code = C.new_recovery_code()
    assert len(code.replace("-", "")) == 32
    rs = C.new_salt()
    kek_r, _ = C.recovery_keys(code, rs)
    wrapped = C.wrap(kek_r, mk, b"sv-mk")
    assert C.unwrap(C.recovery_keys(code.lower().replace("-", " "), rs)[0], wrapped, b"sv-mk") == mk
    with pytest.raises(C.CryptoError):
        C.unwrap(C.recovery_keys(C.new_recovery_code(), rs)[0], wrapped, b"sv-mk")
    with pytest.raises(C.CryptoError):
        C.recovery_keys("ABC", rs)


def test_recovery_codes_are_unique():
    assert len({C.new_recovery_code() for _ in range(200)}) == 200


def test_content_tag_is_key_dependent():
    import hashlib
    h = hashlib.sha256(b"x").digest()
    assert C.content_tag(b"a" * 32, h) != C.content_tag(b"b" * 32, h)
    assert C.content_tag(b"a" * 32, h) == C.content_tag(b"a" * 32, h)
