"""Authenticated envelope encryption and KMS provider abstraction (pure stdlib)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
from typing import Protocol, runtime_checkable


class KMSError(ValueError):
    """Raised when envelope encryption, key unwrapping, or authentication fails."""


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _derive_subkeys(key_bytes: bytes) -> tuple[bytes, bytes]:
    """Derive independent encryption and MAC keys from a 256-bit key."""
    master = hashlib.sha256(key_bytes).digest()
    enc_key = hmac.new(master, b"aegis-kms-enc-v1", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"aegis-kms-mac-v1", hashlib.sha256).digest()
    return enc_key, mac_key


def _canonical_aad(context: dict[str, str] | None) -> bytes:
    if not context:
        return b""
    return json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_ctr_xor(enc_key: bytes, nonce: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hmac.new(enc_key, nonce + struct.pack(">Q", counter), hashlib.sha256).digest()
        chunk_len = min(len(block), len(data) - offset)
        for idx in range(chunk_len):
            out[offset + idx] = data[offset + idx] ^ block[idx]
        offset += chunk_len
        counter += 1
    return bytes(out)


def _aead_encrypt(key_bytes: bytes, plaintext: bytes, *, aad: bytes = b"") -> tuple[bytes, bytes, bytes]:
    enc_key, mac_key = _derive_subkeys(key_bytes)
    nonce = os.urandom(16)
    ciphertext = _hmac_ctr_xor(enc_key, nonce, plaintext)
    auth_input = struct.pack(">I", len(aad)) + aad + nonce + ciphertext
    tag = hmac.new(mac_key, auth_input, hashlib.sha256).digest()
    return nonce, ciphertext, tag


def _aead_decrypt(key_bytes: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, *, aad: bytes = b"") -> bytes:
    if len(nonce) != 16 or len(tag) != 32:
        raise KMSError("Malformed ciphertext nonce or authentication tag")
    enc_key, mac_key = _derive_subkeys(key_bytes)
    auth_input = struct.pack(">I", len(aad)) + aad + nonce + ciphertext
    expected_tag = hmac.new(mac_key, auth_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_tag, tag):
        raise KMSError("Ciphertext authentication tag verification failed")
    return _hmac_ctr_xor(enc_key, nonce, ciphertext)


@runtime_checkable
class KMSProvider(Protocol):
    """Protocol for external or local Key Management Service key-wrapping providers."""

    key_id: str

    def wrap_key(self, plaintext_key: bytes, *, context: dict[str, str] | None = None) -> bytes: ...

    def unwrap_key(self, wrapped_key: bytes, *, context: dict[str, str] | None = None) -> bytes: ...


class LocalKMSProvider:
    """In-process versioned KEK provider supporting key rotation and AAD context binding."""

    def __init__(
        self,
        master_secret: str | bytes | None = None,
        *,
        key_id: str = "local-v1",
        keyring: dict[str, str | bytes] | None = None,
    ) -> None:
        self._keys: dict[str, bytes] = {}
        if keyring:
            for kid, secret in keyring.items():
                self._keys[kid] = secret.encode("utf-8") if isinstance(secret, str) else secret
        if master_secret is not None:
            raw = master_secret.encode("utf-8") if isinstance(master_secret, str) else master_secret
            if not raw:
                raise KMSError("Master secret must not be empty")
            self._keys[key_id] = raw
        if not self._keys:
            raise KMSError("At least one master key must be configured")
        if key_id not in self._keys:
            raise KMSError(f"Active key_id '{key_id}' not found in keyring")
        for kid, raw in self._keys.items():
            if not raw:
                raise KMSError(f"Key '{kid}' must not be empty")
        self.key_id = key_id

    def wrap_key(self, plaintext_key: bytes, *, context: dict[str, str] | None = None) -> bytes:
        if not plaintext_key:
            raise KMSError("Plaintext data key must not be empty")
        aad = _canonical_aad(context)
        nonce, ciphertext, tag = _aead_encrypt(self._keys[self.key_id], plaintext_key, aad=aad)
        envelope = f"wk1.{_b64u_encode(self.key_id.encode('utf-8'))}.{_b64u_encode(nonce)}.{_b64u_encode(ciphertext)}.{_b64u_encode(tag)}"
        return envelope.encode("ascii")

    def unwrap_key(self, wrapped_key: bytes, *, context: dict[str, str] | None = None) -> bytes:
        try:
            parts = wrapped_key.decode("ascii").split(".")
            if len(parts) != 5 or parts[0] != "wk1":
                raise KMSError("Unsupported wrapped key format")
            kid = _b64u_decode(parts[1]).decode("utf-8")
            nonce = _b64u_decode(parts[2])
            ciphertext = _b64u_decode(parts[3])
            tag = _b64u_decode(parts[4])
        except KMSError:
            raise
        except Exception as exc:
            raise KMSError("Corrupted wrapped data key") from exc

        kek = self._keys.get(kid)
        if kek is None:
            raise KMSError(f"Unknown key_id '{kid}'")
        aad = _canonical_aad(context)
        return _aead_decrypt(kek, nonce, ciphertext, tag, aad=aad)


class EnvelopeCipher:
    """Versioned envelope encryption using per-secret DEKs wrapped by a KMSProvider."""

    def __init__(
        self,
        provider: KMSProvider | None = None,
        *,
        master_secret: str | bytes | None = None,
        key_id: str = "local-v1",
    ) -> None:
        if provider is not None:
            self.provider = provider
        else:
            self.provider = LocalKMSProvider(master_secret=master_secret, key_id=key_id)

    def wrap_data_key(self, data_key: bytes, *, context: dict[str, str] | None = None) -> str:
        wrapped = self.provider.wrap_key(data_key, context=context)
        return wrapped.decode("ascii")

    def unwrap_data_key(self, wrapped_token: str, *, context: dict[str, str] | None = None) -> bytes:
        return self.provider.unwrap_key(wrapped_token.encode("ascii"), context=context)

    def encrypt_secret(self, plaintext: str | bytes, *, context: dict[str, str] | None = None) -> str:
        plaintext_bytes = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        dek = os.urandom(32)
        wrapped_dek = self.provider.wrap_key(dek, context=context)
        aad = _canonical_aad(context)
        nonce, ciphertext, tag = _aead_encrypt(dek, plaintext_bytes, aad=aad)
        return ".".join([
            "v1",
            _b64u_encode(self.provider.key_id.encode("utf-8")),
            _b64u_encode(wrapped_dek),
            _b64u_encode(nonce),
            _b64u_encode(ciphertext),
            _b64u_encode(tag),
        ])

    def decrypt_secret_bytes(self, token: str, *, context: dict[str, str] | None = None) -> bytes:
        try:
            parts = token.strip().split(".")
            if len(parts) != 6 or parts[0] != "v1":
                raise KMSError("Unsupported envelope ciphertext format")
            _ = _b64u_decode(parts[1]).decode("utf-8")
            wrapped_dek = _b64u_decode(parts[2])
            nonce = _b64u_decode(parts[3])
            ciphertext = _b64u_decode(parts[4])
            tag = _b64u_decode(parts[5])
        except KMSError:
            raise
        except Exception as exc:
            raise KMSError("Corrupted envelope ciphertext") from exc

        dek = self.provider.unwrap_key(wrapped_dek, context=context)
        aad = _canonical_aad(context)
        return _aead_decrypt(dek, nonce, ciphertext, tag, aad=aad)

    def decrypt_secret(self, token: str, *, context: dict[str, str] | None = None) -> str:
        try:
            return self.decrypt_secret_bytes(token, context=context).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KMSError("Decrypted secret is not valid UTF-8") from exc


def wrap_data_key(
    data_key: bytes,
    *,
    master_secret: str | bytes,
    key_id: str = "local-v1",
    context: dict[str, str] | None = None,
) -> str:
    return EnvelopeCipher(master_secret=master_secret, key_id=key_id).wrap_data_key(data_key, context=context)


def unwrap_data_key(
    wrapped_token: str,
    *,
    master_secret: str | bytes,
    key_id: str = "local-v1",
    context: dict[str, str] | None = None,
) -> bytes:
    return EnvelopeCipher(master_secret=master_secret, key_id=key_id).unwrap_data_key(wrapped_token, context=context)


def encrypt_secret(
    plaintext: str | bytes,
    *,
    master_secret: str | bytes,
    key_id: str = "local-v1",
    context: dict[str, str] | None = None,
) -> str:
    return EnvelopeCipher(master_secret=master_secret, key_id=key_id).encrypt_secret(plaintext, context=context)


def decrypt_secret(
    token: str,
    *,
    master_secret: str | bytes,
    key_id: str = "local-v1",
    context: dict[str, str] | None = None,
) -> str:
    return EnvelopeCipher(master_secret=master_secret, key_id=key_id).decrypt_secret(token, context=context)
