"""J-Quants provider error taxonomy.

Every error carries a stable ``code`` string so worker task status and the
data-status page can report failures without leaking payloads or the API key.
"""

from __future__ import annotations


class JQuantsError(Exception):
    """Base class for all J-Quants provider failures."""

    code = "jquants_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.code)
        if code is not None:
            self.code = code


class JQuantsConfigError(JQuantsError):
    """The provider is not configured (missing API key)."""

    code = "jquants_not_configured"


class JQuantsAuthError(JQuantsError):
    """401/403 — invalid key, expired subscription, or endpoint not in plan."""

    code = "jquants_auth_failed"


class JQuantsPlanError(JQuantsAuthError):
    """The endpoint exists but is not included in the current subscription."""

    code = "jquants_plan_not_included"


class JQuantsRetryableError(JQuantsError):
    """Transient failure; the caller may retry with backoff."""

    code = "jquants_retryable"


class JQuantsRateLimited(JQuantsRetryableError):
    """429 — the documented behavior escalates to a ~5 minute block when
    grossly exceeded, so the retry delay must be honored, never shortened."""

    code = "jquants_rate_limited"

    def __init__(self, message: str = "", *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class JQuantsServerError(JQuantsRetryableError):
    code = "jquants_server_error"


class JQuantsTimeout(JQuantsRetryableError):
    code = "jquants_timeout"


class JQuantsTransportError(JQuantsRetryableError):
    code = "jquants_transport_error"


class JQuantsSchemaError(JQuantsError):
    """The response did not match the documented shape. Never retried —
    a schema drift needs code changes, not another request."""

    code = "jquants_schema_error"


class JQuantsPayloadTooLarge(JQuantsError):
    code = "jquants_payload_too_large"


__all__ = [
    "JQuantsAuthError",
    "JQuantsConfigError",
    "JQuantsError",
    "JQuantsPayloadTooLarge",
    "JQuantsPlanError",
    "JQuantsRateLimited",
    "JQuantsRetryableError",
    "JQuantsSchemaError",
    "JQuantsServerError",
    "JQuantsTimeout",
    "JQuantsTransportError",
]
