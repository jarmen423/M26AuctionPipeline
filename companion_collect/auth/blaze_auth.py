"""Blaze Companion auth bundle generation.

This module now contains a first-cut implementation of the auth material
reverse‑engineered from native symbols referenced as
``EA::Online::Security::MessageAuthHelper``. It intentionally keeps the logic
small and *pure* so we can unit test and later swap out pieces if additional
crypto stages are discovered.

Current working model (v1 / experimental):
 1. Build a JSON payload: ``{"staticData": STATIC_KEY, "requestId": <u32>, "blazeId": <int>}``
     (optionally adds ``additionalData`` if provided).
 2. Prepend a 4‑byte random nonce.
 3. Derive a 16‑byte keystream = MD5(nonce || PROCESS_DATA_CONSTANT).
 4. XOR each payload byte (post‑nonce) with the repeating keystream (native
     ``ProcessData`` behaviour).
 5. authData = resulting nonce + XORed bytes (base64 encoded in the request).
 6. authCode = MD5(AUTH_CODE_SALT || authData) (base64 encoded in the request).

Captured traffic shows the server currently validates the salted MD5 over the
wire blob. If later captures reveal an *additional* transform before XOR (our
open research risk) we can insert it between steps (1) and (2) without changing
the public function contract below.

Limitations / TODO:
 * The exact contents of the JSON inside authData are still partially inferred.
    If we confirm new fields we will extend ``_build_payload`` (backwards
    compatible by keeping existing keys stable).
 * A future version may replace MD5 with whatever the native helper ultimately
    feeds (if MD5 is only an inner step). Tests will pin behaviour so changes are
    deliberate.

WARNING: This implementation is marked *experimental*. Set environment variable
``COMPANION_EXPERIMENTAL_AUTH=1`` (or pass ``experimental=True``) to opt in.
Downstream callers should gracefully handle failures and fall back to captured
fixtures during development.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import secrets
from typing import Final, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio
from functools import wraps

PROCESS_DATA_CONSTANT: Final[bytes] = bytes.fromhex("634203362017bf72f70ba900c0aa4e6b")
AUTH_CODE_SALT: Final[bytes] = bytes.fromhex("3a53413521464c3b6531326530705b70203a2900")
STATIC_KEY: Final[str] = "05e6a7ead5584ab4"  # Observed constant in native payload builder

DEFAULT_AUTH_TYPE: Final[int] = 17_039_361  # 0x01040001 in hex, observed in captures.
DEFAULT_EXPIRATION_LEEWAY_SECONDS: Final[int] = 60


@dataclass(slots=True)
class AuthBundle:
    """Container for the auth material used inside ``messageAuthData``."""

    auth_code: str
    auth_data: str
    auth_type: int
    expires_at: datetime

    def is_expired(self, *, at: datetime | None = None) -> bool:
        """Return ``True`` if the bundle has expired relative to ``at`` (UTC)."""

        check_time = at or datetime.now(tz=timezone.utc)
        return check_time >= self.expires_at


def _derive_keystream(nonce: bytes) -> bytes:
    if len(nonce) != 4:  # pragma: no cover - defensive, enforced by caller
        raise ValueError("nonce must be 4 bytes")
    return hashlib.md5(nonce + PROCESS_DATA_CONSTANT).digest()


def _process_data(buffer: bytes) -> bytes:
    """Mirror native ProcessData (XOR in-place after 4-byte nonce)."""

    if len(buffer) < 4:
        raise ValueError("buffer must include a 4-byte nonce prefix")
    nonce = buffer[:4]
    keystream = _derive_keystream(nonce)
    out = bytearray(buffer)
    for idx in range(4, len(out)):
        out[idx] ^= keystream[(idx - 4) % len(keystream)]
    return bytes(out)


def _build_payload(*, request_id: int, blaze_id: int, additional: str | None = None) -> bytes:
    payload = {
        "staticData": STATIC_KEY,
        "requestId": request_id & 0xFFFFFFFF,
        "blazeId": blaze_id,
    }
    if additional:
        payload["additionalData"] = additional
    # Compact JSON (separators) to match on-device serializer style
    import json

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _compute_auth_code(encrypted_blob: bytes) -> bytes:
    return hashlib.md5(AUTH_CODE_SALT + encrypted_blob).digest()


def compute_message_auth(
    session_key: bytes,
    *,
    device_id: str,
    request_id: int,
    blaze_id: int,
    additional_data: str | None = None,
    message_expiration: datetime | None = None,
    sequence: int | None = None,
    experimental: bool | None = None,
    nonce_override: bytes | None = None,
) -> AuthBundle:
    """Compute a fresh ``AuthBundle`` (experimental MD5/XOR strategy).

    Parameters are intentionally explicit so future algorithm upgrades can keep
    the public signature while ignoring legacy-only arguments.
    """

    del session_key, device_id, sequence, experimental  # Reserved for future deeper algorithm

    expires_at = message_expiration or (datetime.now(tz=timezone.utc) + timedelta(minutes=5))

    nonce = nonce_override or secrets.token_bytes(4)
    if len(nonce) != 4:
        raise ValueError("nonce_override must be exactly 4 bytes if provided")

    plaintext = nonce + _build_payload(request_id=request_id, blaze_id=blaze_id, additional=additional_data)
    encrypted = _process_data(plaintext)
    auth_code_raw = _compute_auth_code(encrypted)

    auth_code_b64 = base64.b64encode(auth_code_raw).decode("ascii")
    auth_data_b64 = base64.b64encode(encrypted).decode("ascii")

    return AuthBundle(
        auth_code=auth_code_b64,
        auth_data=auth_data_b64,
        auth_type=DEFAULT_AUTH_TYPE,
        expires_at=expires_at,
    )


def delta_refresh(
    existing_bundle: AuthBundle,
    *,
    request_id: int,
    blaze_id: int,
    additional_data: str | None = None,
    message_expiration: datetime | None = None,
    nonce_override: bytes | None = None,
) -> AuthBundle:
    """
    Perform delta refresh on an existing AuthBundle by generating a new nonce
    and recomputing auth_code/auth_data without full session re-authentication.
    
    Builds on snallabot patterns for efficient token updates on 401/403 errors.
    Reuses existing auth_type and expiration (or overrides).
    """
    expires_at = message_expiration or existing_bundle.expires_at

    nonce = nonce_override or secrets.token_bytes(4)
    if len(nonce) != 4:
        raise ValueError("nonce_override must be exactly 4 bytes if provided")

    plaintext = nonce + _build_payload(request_id=request_id, blaze_id=blaze_id, additional=additional_data)
    encrypted = _process_data(plaintext)
    auth_code_raw = _compute_auth_code(encrypted)

    auth_code_b64 = base64.b64encode(auth_code_raw).decode("ascii")
    auth_data_b64 = base64.b64encode(encrypted).decode("ascii")

    return AuthBundle(
        auth_code=auth_code_b64,
        auth_data=auth_data_b64,
        auth_type=existing_bundle.auth_type,
        expires_at=expires_at,
    )


def retry_on_error(max_retries: int = 3, base_backoff: float = 1.0):
    """
    Decorator for async retry with exponential backoff on errors (e.g., for 401/403 handling at auth level).
    Runs sync function in thread pool.
    """
    def decorator(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    # Run sync f in thread to allow async context
                    return await asyncio.to_thread(f, *args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        sleep_time = base_backoff * (2 ** attempt)
                        await asyncio.sleep(sleep_time)
                    else:
                        raise last_exception
            return None  # Unreachable
        return wrapper
    return decorator


@retry_on_error(max_retries=3, base_backoff=2.0)
async def compute_message_auth_async(
    session_key: bytes,
    *,
    device_id: str,
    request_id: int,
    blaze_id: int,
    additional_data: str | None = None,
    message_expiration: datetime | None = None,
    sequence: int | None = None,
    experimental: bool | None = None,
    nonce_override: bytes | None = None,
) -> AuthBundle:
    """Async wrapper for compute_message_auth with retry on errors."""
    return compute_message_auth(
        session_key=session_key,
        device_id=device_id,
        request_id=request_id,
        blaze_id=blaze_id,
        additional_data=additional_data,
        message_expiration=message_expiration,
        sequence=sequence,
        experimental=experimental,
        nonce_override=nonce_override,
    )


@retry_on_error(max_retries=3, base_backoff=2.0)
async def delta_refresh_async(
    existing_bundle: AuthBundle,
    *,
    request_id: int,
    blaze_id: int,
    additional_data: str | None = None,
    message_expiration: datetime | None = None,
    nonce_override: bytes | None = None,
) -> AuthBundle:
    """Async wrapper for delta_refresh with retry on errors."""
    return delta_refresh(
        existing_bundle=existing_bundle,
        request_id=request_id,
        blaze_id=blaze_id,
        additional_data=additional_data,
        message_expiration=message_expiration,
        nonce_override=nonce_override,
    )


def decode_auth_data(auth_data_b64: str) -> Tuple[str, str]:
    """Decode a base64 ``authData`` blob returning (nonce_hex, inner_json_str).

    This mirrors the inverse of our experimental pipeline: base64 decode, leave
    the first 4 bytes (nonce) untouched, XOR the remainder using the derived
    keystream, then UTF-8 decode the plaintext JSON.
    """

    raw = base64.b64decode(auth_data_b64)
    if len(raw) < 5:  # pragma: no cover - defensive guard
        raise ValueError("authData too short")
    nonce = raw[:4]
    processed = _process_data(raw)  # applying ProcessData again decrypts
    payload = processed[4:]
    try:
        payload_str = payload.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - diagnostic
        raise ValueError("Decrypted payload is not valid UTF-8") from exc
    return nonce.hex(), payload_str


__all__ = ["AuthBundle", "compute_message_auth", "decode_auth_data", "DEFAULT_AUTH_TYPE", "delta_refresh", "compute_message_auth_async", "delta_refresh_async"]
