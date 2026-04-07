"""HTTP client for MoneyForward Cloud Invoice API with rate limiting."""

from __future__ import annotations

import time
from typing import Any

import requests

from autoinvoice.moneyforward.auth import MFOAuthManager

BASE_URL = "https://invoice.moneyforward.com/api/v3"
MAX_REQUESTS_PER_SEC = 3


class MFClient:
    """HTTP client for MoneyForward Cloud Invoice API."""

    def __init__(self, auth_manager: MFOAuthManager):
        self._auth = auth_manager
        self._session = requests.Session()
        self._last_request_times: list[float] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        """Send a GET request."""
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict | None = None) -> dict:
        """Send a POST request."""
        return self._request("POST", path, json_data=data)

    def put(self, path: str, data: dict | None = None) -> dict:
        """Send a PUT request."""
        return self._request("PUT", path, json_data=data)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict:
        """Send an HTTP request with auth, rate limiting, and retry."""
        self._rate_limit()
        url = f"{BASE_URL}{path}"

        for attempt in range(3):
            token = self._auth.get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            resp = self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=30,
            )

            # Handle 401 (token expired)
            if resp.status_code == 401 and attempt < 2:
                self._auth._refresh_token()
                continue

            # Handle 429 (rate limited)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"API request failed after 3 attempts: {method} {path}")

    def _rate_limit(self) -> None:
        """Enforce rate limit of MAX_REQUESTS_PER_SEC."""
        now = time.time()
        # Remove entries older than 1 second
        self._last_request_times = [
            t for t in self._last_request_times if now - t < 1.0
        ]
        if len(self._last_request_times) >= MAX_REQUESTS_PER_SEC:
            sleep_time = 1.0 - (now - self._last_request_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        self._last_request_times.append(time.time())
