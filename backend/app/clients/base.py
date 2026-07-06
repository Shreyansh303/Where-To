"""Shared HTTP plumbing for all external API clients.

Cross-cutting concerns live here so each concrete client is only parsing:
- error taxonomy (auth vs rate-limit vs transient outage vs hard failure)
- exponential backoff with retry on 429/5xx and network errors
- cache-first request helper (API keys are injected at request time and are
  never part of the cache signature)
- a counter of real HTTP calls made, so cache effectiveness is measurable
"""

import time
from typing import Any, Callable

import httpx

from ..cache import Cache


class ApiError(Exception):
    def __init__(self, source: str, message: str, status: int | None = None):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.status = status


class ApiAuthError(ApiError):
    """Bad/missing API key — retrying is pointless."""


class ApiRateLimitError(ApiError):
    """429 after all retries — caller should degrade gracefully."""


class ApiUnavailableError(ApiError):
    """5xx or network failure after all retries."""


_RETRYABLE = {429, 500, 502, 503, 504}


class BaseClient:
    service = "base"

    def __init__(
        self,
        cache: Cache | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cache = cache
        self.calls_made = 0
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
    ) -> Any:
        last_error: ApiError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
            try:
                resp = self._http.request(method, url, params=params, json=json_body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = ApiUnavailableError(self.service, f"network error: {exc}")
                continue
            if resp.status_code in (401, 403):
                raise ApiAuthError(self.service, "authentication failed — check API key", resp.status_code)
            if resp.status_code in _RETRYABLE:
                err_cls = ApiRateLimitError if resp.status_code == 429 else ApiUnavailableError
                last_error = err_cls(self.service, f"HTTP {resp.status_code}", resp.status_code)
                continue
            if resp.is_success:
                self.calls_made += 1
                return resp.json()
            raise ApiError(self.service, f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
        assert last_error is not None
        raise last_error

    def _cached_json(
        self,
        cache_params: dict[str, Any],
        fetch: Callable[[], Any],
        no_cache: bool = False,
    ) -> Any:
        """Return the cached response for this request signature, or perform
        the real call and cache it. `cache_params` must uniquely describe the
        request but exclude secrets."""
        if self.cache is not None and not no_cache:
            hit = self.cache.get(self.service, cache_params)
            if hit is not None:
                return hit
        raw = fetch()
        if self.cache is not None:
            self.cache.set(self.service, cache_params, raw)
        return raw

    def close(self) -> None:
        self._http.close()
