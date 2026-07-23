"""Framework-independent helpers for the Zadarma cloud PBX API.

Every call-site that talks to Zadarma (click-to-call, bulk import, balance
dashboard, recording fetch, webhook signature check) used to hand-roll its
own copy of the HMAC-SHA1 request signing recipe and the rate-limit /
phone-normalization checks. That duplication is consolidated here into pure
functions with no Odoo ORM dependency, so it can be unit-tested with plain
pytest and imported from any model or controller.

Zadarma request-signing recipe (documented at zadarma.com/en/support/api/):
    query_string = urlencode(sorted(params.items()))
    md5_hex      = md5(query_string).hexdigest()
    signature    = base64(hmac_sha1(secret, method + query_string + md5_hex))
    Authorization: "<key>:<signature>"

MD5 is mandated by the Zadarma protocol itself, not a security choice made
here — see ``usedforsecurity=False`` below and the ``bandit``/``ruff`` skip
comments at each call-site.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from urllib.parse import urlencode

_RATE_LIMIT_MARKER = 'rate limit'

# Two HMAC-SHA1 signature variants have been observed across different
# versions of the Zadarma webhook docs; both are checked against the
# incoming `Signature` header (see `verify_webhook_signature`).
WEBHOOK_SIGNATURE_HEADERS = ('Signature', 'X-Signature', 'Zadarma-Signature')


def compute_signature(secret: str, method: str, params: dict[str, object]) -> tuple[str, str]:
    """Build the Zadarma ``Authorization`` header value for a request.

    :param secret: Zadarma API secret (``res.company.zadarma_api_secret``).
    :param method: API path, e.g. ``/v1/statistics/pbx/``.
    :param params: request query parameters (not yet URL-encoded).
    :return: ``(query_string, signature)`` — the caller builds the final URL
        as ``f"https://api.zadarma.com{method}?{query_string}"`` and sends
        header ``Authorization: f"{key}:{signature}"``.
    """
    query_string = urlencode(sorted(params.items()))
    md5_hex = hashlib.md5(query_string.encode(), usedforsecurity=False).hexdigest()  # noqa: S324
    sign_str = method + query_string + md5_hex
    digest = hmac.new(secret.encode(), sign_str.encode(), hashlib.sha1).hexdigest()
    signature = base64.b64encode(digest.encode()).decode()
    return query_string, signature


def is_rate_limited(status_code: int, body: dict[str, object] | None) -> bool:
    """True if a Zadarma API response indicates the account hit its rate limit.

    Zadarma signals rate-limiting two different ways depending on the
    endpoint: an HTTP 429, or an HTTP 200 with
    ``{"status": "error", "message": "...rate limit..."}`` in the body —
    both must be handled to avoid silently dropping calls under load.
    """
    if status_code == 429:
        return True
    if isinstance(body, dict) and body.get('status') == 'error':
        message = str(body.get('message') or '').lower()
        return _RATE_LIMIT_MARKER in message
    return False


def normalize_phone(phone: str | None) -> str:
    """Strip everything but digits. Canonical normalization shared by
    webhook, bulk import, and orphan-partner re-match — a phone is only
    ever compared by its digit suffix, never as a raw string."""
    if not phone:
        return ''
    return re.sub(r'\D', '', str(phone))


def normalize_status(raw: str | None, whitelist: frozenset[str], fallback: str) -> str | bool:
    """Normalize a Zadarma ``disposition`` value to a whitelisted key.

    Guarantees the result can always be written to the ``status`` Selection
    field. An unrecognized value logs a warning upstream and falls back to
    ``fallback`` rather than raising, so a call is never lost to a
    ValueError on an unexpected future Zadarma status string.
    """
    if not raw:
        return False
    normalized = str(raw).strip().lower()
    return normalized if normalized in whitelist else fallback


def compute_webhook_signatures(secret: str, sorted_params_string: str) -> tuple[str, str]:
    """Compute both known webhook signature variants for comparison against
    the incoming ``Signature`` header.

    Variant A: base64(hmac_sha1(secret, sorted_params_string))
    Variant B: base64(hmac_sha1(secret, md5_hex(sorted_params_string)))
    """
    sig_a = base64.b64encode(
        hmac.new(secret.encode(), sorted_params_string.encode(), hashlib.sha1).digest()
    ).decode()
    md5_hex = hashlib.md5(sorted_params_string.encode(), usedforsecurity=False).hexdigest()  # noqa: S324
    sig_b = base64.b64encode(
        hmac.new(secret.encode(), md5_hex.encode(), hashlib.sha1).digest()
    ).decode()
    return sig_a, sig_b


def verify_webhook_signature(secret: str, sorted_params_string: str, signature: str) -> str | None:
    """Compare an incoming webhook signature against both known variants.

    :return: ``'A'`` or ``'B'`` if one variant matches, else ``None``.
    """
    sig_a, sig_b = compute_webhook_signatures(secret, sorted_params_string)
    if hmac.compare_digest(sig_a, signature):
        return 'A'
    if hmac.compare_digest(sig_b, signature):
        return 'B'
    return None
