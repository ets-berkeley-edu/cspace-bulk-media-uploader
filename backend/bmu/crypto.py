"""Encryption of CollectionSpace passwords at rest.

Two purposes use separate keys, as in the design: "session" (while signed in) and "job"
(from scheduling until the job's run ends, at most 72 hours). The encryption context binds a
ciphertext to its user and session or job, so it can't be replayed elsewhere.

- LocalCrypto: AES-256-GCM with keys from the environment (development only).
- KmsCrypto: envelope encryption with a KMS data key per value (AWS).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import Settings


class Crypto(Protocol):
    def encrypt(self, purpose: str, plaintext: str, context: dict[str, str]) -> str: ...
    def decrypt(self, purpose: str, token: str, context: dict[str, str]) -> str: ...


def _aad(purpose: str, context: dict[str, str]) -> bytes:
    return json.dumps({"purpose": purpose, **context}, sort_keys=True).encode()


class LocalCrypto:
    def __init__(self, keys: dict[str, bytes]):
        for p, k in keys.items():
            if len(k) != 32:
                raise ValueError(f"{p} key must be 32 bytes")
        self._keys = keys

    def encrypt(self, purpose: str, plaintext: str, context: dict[str, str]) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[purpose]).encrypt(nonce, plaintext.encode(), _aad(purpose, context))
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, purpose: str, token: str, context: dict[str, str]) -> str:
        raw = base64.b64decode(token)
        return AESGCM(self._keys[purpose]).decrypt(raw[:12], raw[12:], _aad(purpose, context)).decode()


class KmsCrypto:
    def __init__(self, kms, key_ids: dict[str, str]):
        self._kms = kms
        self._key_ids = key_ids

    def encrypt(self, purpose: str, plaintext: str, context: dict[str, str]) -> str:
        ctx = {"purpose": purpose, **context}
        dk = self._kms.generate_data_key(KeyId=self._key_ids[purpose], KeySpec="AES_256", EncryptionContext=ctx)
        nonce = os.urandom(12)
        ct = AESGCM(dk["Plaintext"]).encrypt(nonce, plaintext.encode(), _aad(purpose, context))
        return json.dumps({"k": base64.b64encode(dk["CiphertextBlob"]).decode(),
                           "c": base64.b64encode(nonce + ct).decode()})

    def decrypt(self, purpose: str, token: str, context: dict[str, str]) -> str:
        env = json.loads(token)
        ctx = {"purpose": purpose, **context}
        key = self._kms.decrypt(CiphertextBlob=base64.b64decode(env["k"]), EncryptionContext=ctx)["Plaintext"]
        raw = base64.b64decode(env["c"])
        return AESGCM(key).decrypt(raw[:12], raw[12:], _aad(purpose, context)).decode()


def make_crypto(settings: Settings, kms_client=None) -> Crypto:
    if settings.crypto_mode == "kms":
        import boto3

        kms = kms_client or boto3.client("kms", region_name=settings.aws_region)
        return KmsCrypto(kms, {"session": settings.kms_session_key_id or "", "job": settings.kms_job_key_id or ""})
    if not settings.session_key_b64 or not settings.job_key_b64:
        raise RuntimeError("Set BMU_SESSION_KEY_B64 and BMU_JOB_KEY_B64 (32 random bytes, base64) for local crypto")
    return LocalCrypto({"session": base64.b64decode(settings.session_key_b64),
                        "job": base64.b64decode(settings.job_key_b64)})
