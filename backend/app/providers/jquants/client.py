"""J-Quants API V2 HTTP client.

Design rules:
- V2 only: base ``https://api.jquants.com/v2`` with the ``x-api-key`` header.
  The retired V1 token flow is intentionally not implemented.
- Synchronous by design — sync tasks run inside worker threads, and the
  Standard-plan rate budget (120/min) makes request concurrency pointless.
- Every page fetch passes through the shared rate limiter; 429 responses
  block *all* buckets because the documented escalation is a full block.
- The API key never appears in errors, logs, or repr output.
"""

from __future__ import annotations

import gzip
import io
import json
import random
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import httpx

from .errors import (
    JQuantsAuthError,
    JQuantsConfigError,
    JQuantsError,
    JQuantsPayloadTooLarge,
    JQuantsPlanError,
    JQuantsRateLimited,
    JQuantsSchemaError,
    JQuantsServerError,
    JQuantsTimeout,
    JQuantsTransportError,
)
from .rate_limit import JQuantsRateLimits

OFFICIAL_BASE_URL = "https://api.jquants.com/v2"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # bulk daily files are large
DEFAULT_MAX_PAGES = 2000
# 429 without Retry-After: the docs describe a ~5 minute escalation block,
# so the client backs off far enough to stay out of it.
RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS = 65.0


class JQuantsClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OFFICIAL_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        rate_limits: JQuantsRateLimits | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise JQuantsConfigError("JQUANTS_API_KEY is not configured")
        if not base_url.startswith("https://"):
            raise JQuantsConfigError("J-Quants base URL must be HTTPS")
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max(1, int(max_attempts))
        self._max_response_bytes = int(max_response_bytes)
        self._rate_limits = rate_limits or JQuantsRateLimits()
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "x-api-key": key,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "optix-japan/1.0",
            },
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "JQuantsClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low level ---------------------------------------------------------

    def _request_once(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        self._rate_limits.acquire_for_path(path, sleep=self._sleep)
        try:
            response = self._client.get(path, params=dict(params))
        except httpx.TimeoutException as exc:
            raise JQuantsTimeout(f"timeout on {path}") from exc
        except httpx.HTTPError as exc:
            raise JQuantsTransportError(f"transport failure on {path}") from exc

        status = response.status_code
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            cooldown = retry_after if retry_after is not None else RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS
            self._rate_limits.block_all_for(cooldown)
            raise JQuantsRateLimited(f"rate limited on {path}", retry_after_seconds=cooldown)
        if status in (401,):
            raise JQuantsAuthError(f"authentication rejected on {path}")
        if status == 403:
            # 403 covers both a bad key and an endpoint outside the plan;
            # the caller decides via the capability declaration.
            raise JQuantsPlanError(f"access forbidden on {path}")
        if status >= 500:
            raise JQuantsServerError(f"server error {status} on {path}")
        if status >= 400:
            raise JQuantsError(f"unexpected status {status} on {path}", code="jquants_bad_request")

        content = response.content
        if len(content) > self._max_response_bytes:
            raise JQuantsPayloadTooLarge(f"response exceeded byte budget on {path}")
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise JQuantsSchemaError(f"non-JSON response on {path}") from exc
        if not isinstance(payload, dict):
            raise JQuantsSchemaError(f"unexpected payload shape on {path}")
        return payload

    def _request(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._request_once(path, params)
            except JQuantsRateLimited as exc:
                if attempt >= self._max_attempts:
                    raise
                # The limiter is already blocked; acquire() will wait it out.
                self._sleep(min(exc.retry_after_seconds or 1.0, 120.0))
            except (JQuantsServerError, JQuantsTimeout, JQuantsTransportError):
                if attempt >= self._max_attempts:
                    raise
                backoff = min(30.0, 0.5 * (2 ** (attempt - 1)))
                self._sleep(backoff + random.uniform(0.0, 0.25 * backoff))

    # -- public API --------------------------------------------------------

    def fetch_page(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        clean = {k: str(v) for k, v in (params or {}).items() if v is not None and str(v) != ""}
        return self._request(path, clean)

    def fetch_rows(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Iterator[dict[str, Any]]:
        """Yield every row across ``pagination_key`` pages."""

        base = {k: str(v) for k, v in (params or {}).items() if v is not None and str(v) != ""}
        pagination_key: str | None = None
        for _ in range(max_pages):
            page_params = dict(base)
            if pagination_key:
                page_params["pagination_key"] = pagination_key
            payload = self._request(path, page_params)
            rows = payload.get("data")
            if rows is None:
                # Some endpoints keep their V1-style envelope key; accept any
                # single list-valued field rather than guessing names.
                rows = _single_list_value(payload)
            if not isinstance(rows, list):
                raise JQuantsSchemaError(f"missing data array on {path}")
            for row in rows:
                if isinstance(row, dict):
                    yield row
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                return
        raise JQuantsSchemaError(f"pagination did not terminate within {max_pages} pages on {path}")

    def fetch_all(self, path: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        return list(self.fetch_rows(path, params))

    # -- bulk download -----------------------------------------------------

    def bulk_list(
        self,
        *,
        endpoint: str | None = None,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        if bool(endpoint) == bool(date):
            raise JQuantsError("bulk_list requires exactly one of endpoint or date", code="jquants_bad_request")
        params: dict[str, Any] = {}
        if endpoint:
            params["endpoint"] = endpoint
            if date_from:
                params["from"] = date_from
            if date_to:
                params["to"] = date_to
        else:
            params["date"] = date
        return self.fetch_all("/bulk/list", params)

    def bulk_download_csv(self, key: str) -> io.TextIOBase:
        """Resolve a bulk file key to its presigned URL and stream-decode it."""

        payload = self.fetch_page("/bulk/get", {"key": key})
        url = payload.get("url") or _single_string_value(payload)
        if not isinstance(url, str) or not url.startswith("https://"):
            raise JQuantsSchemaError("bulk/get did not return a presigned https url")
        # Presigned URL: no API key header must ever be attached.
        try:
            with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0), follow_redirects=True) as raw:
                response = raw.get(url)
        except httpx.TimeoutException as exc:
            raise JQuantsTimeout("timeout downloading bulk file") from exc
        except httpx.HTTPError as exc:
            raise JQuantsTransportError("transport failure downloading bulk file") from exc
        if response.status_code != 200:
            raise JQuantsServerError(f"bulk download failed with status {response.status_code}")
        body = response.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return io.StringIO(body.decode("utf-8-sig"))


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if seconds < 0.0:
        return None
    return min(seconds, 600.0)


def _single_list_value(payload: Mapping[str, Any]) -> Any:
    lists = [v for k, v in payload.items() if isinstance(v, list) and k != "pagination_key"]
    return lists[0] if len(lists) == 1 else None


def _single_string_value(payload: Mapping[str, Any]) -> Any:
    strings = [v for k, v in payload.items() if isinstance(v, str) and k != "pagination_key"]
    return strings[0] if len(strings) == 1 else None


__all__ = ["JQuantsClient", "OFFICIAL_BASE_URL"]
