"""
DhanDataProvider: Optional Secondary Helper (NOT Blocking).

This module provides read-only access to Dhan HQ v2 API for supplementary
LTP cross-reference and position verification. The core pipeline runs
fully without Dhan credentials. Keys are optional.

Role: OPTIONAL_SECONDARY_HELPER_NOT_BLOCKING
"""
from __future__ import annotations

import time
import requests


class DhanApiError(Exception):
    """Non-fatal Dhan API error with structured user guidance."""

    def __init__(self, message, user_action=None, raw_response=None):
        super().__init__(message)
        self.user_action = user_action or "Dhan API is optional. The pipeline works without it."
        self.raw_response = raw_response


class DhanDataProvider:
    """Optional Secondary Helper (NOT Blocking). Core pipeline runs with keys blank."""

    def __init__(self, client_id=None, access_token=None, base_url="https://api.dhan.co/v2"):
        self.client_id = client_id
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.connected = False
        self._headers: dict[str, str] = {}

        if client_id and access_token:
            self.connected = True
            self._headers = {
                "access-token": self.access_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def healthcheck(self) -> dict:
        if not self.connected:
            return {
                "status": "disconnected",
                "reason": "No Dhan credentials provided",
                "connected": False,
                "user_action": (
                    "Dhan API is optional. Set DHAN_CLIENT_ID and "
                    "DHAN_ACCESS_TOKEN in .env if you want secondary "
                    "LTP cross-reference."
                ),
            }
        try:
            data = self._get("/funds/fund-summary", timeout=5)
            return {"status": "ok", "connected": True, "data": data}
        except DhanApiError as exc:
            return {
                "status": "error",
                "connected": True,
                "error": str(exc),
                "user_action": exc.user_action,
            }

    def get_today_positions(self) -> dict:
        if not self.connected:
            return {"status": "unavailable", "data": [], "connected": False}
        try:
            data = self._get("/positions")
            return {"status": "ok", "data": data, "connected": True}
        except DhanApiError as exc:
            return {
                "status": "error",
                "data": [],
                "connected": True,
                "error": str(exc),
                "user_action": exc.user_action,
            }

    def get_today_trades(self) -> dict:
        if not self.connected:
            return {"status": "unavailable", "data": [], "connected": False}
        try:
            data = self._get("/trades")
            return {"status": "ok", "data": data, "connected": True}
        except DhanApiError as exc:
            return {
                "status": "error",
                "data": [],
                "connected": True,
                "error": str(exc),
                "user_action": exc.user_action,
            }

    def get_funds_limits(self) -> dict:
        if not self.connected:
            return {"status": "unavailable", "data": {}, "connected": False}
        try:
            data = self._get("/funds/fund-summary")
            return {"status": "ok", "data": data, "connected": True}
        except DhanApiError as exc:
            return {
                "status": "error",
                "data": {},
                "connected": True,
                "error": str(exc),
                "user_action": exc.user_action,
            }

    def get_marketfeed_ltp(self, instruments: list) -> dict:
        if not self.connected:
            return {"status": "unavailable", "data": {}, "connected": False}
        try:
            data = self._post("/marketfeed/ltp", json_body={"instruments": instruments})
            return {"status": "ok", "data": data, "connected": True}
        except DhanApiError as exc:
            return {
                "status": "error",
                "data": {},
                "connected": True,
                "error": str(exc),
                "user_action": exc.user_action,
            }

    # ------------------------------------------------------------------
    # Private HTTP helpers with retry
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 10)
        url = self.base_url + endpoint
        return self._request_with_retry("GET", url, timeout=timeout, **kwargs)

    def _post(self, endpoint: str, json_body: dict, **kwargs) -> dict:
        timeout = kwargs.pop("timeout", 10)
        url = self.base_url + endpoint
        return self._request_with_retry("POST", url, json=json_body, timeout=timeout, **kwargs)

    def _request_with_retry(self, method: str, url: str, **kwargs) -> dict:
        max_retries = 3
        timeout = kwargs.pop("timeout", 10)
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=self._headers, timeout=timeout, **kwargs
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as exc:
                last_exc = exc
                raw = getattr(exc.response, "text", None)
                if exc.response is not None and exc.response.status_code < 500:
                    raise DhanApiError(
                        f"Dhan API HTTP {exc.response.status_code}: {raw}",
                        user_action="Check your Dhan credentials or request parameters.",
                        raw_response=raw,
                    ) from exc
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
            except requests.exceptions.Timeout as exc:
                last_exc = exc

            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        raise DhanApiError(
            f"Dhan API request failed after {max_retries} retries: {last_exc}",
            user_action="Check network connectivity and Dhan API status at https://api.dhan.co.",
            raw_response=None,
        ) from last_exc
