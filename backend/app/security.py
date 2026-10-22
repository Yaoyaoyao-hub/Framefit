"""Anonymous workspace credentials and signed asset URLs."""

import hashlib
import hmac
import secrets
import time

from app.config import get_settings
from app.errors import APIError


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_asset(asset_id: str, ttl_seconds: int = 3600) -> str:
    exp = int(time.time()) + ttl_seconds
    message = f"{asset_id}.{exp}".encode("utf-8")
    signature = hmac.new(get_settings().secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"/api/assets/{asset_id}/content?exp={exp}&sig={signature}"


def verify_asset_signature(asset_id: str, exp: str, sig: str) -> None:
    try:
        expires = int(exp)
    except (TypeError, ValueError) as exc:
        raise APIError(403, "forbidden", "This image link is not valid.") from exc
    if expires < int(time.time()):
        raise APIError(403, "forbidden", "This image link has expired. Refresh the page.")
    message = f"{asset_id}.{expires}".encode("utf-8")
    expected = hmac.new(get_settings().secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig or ""):
        raise APIError(403, "forbidden", "This image link is not valid.")
