from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional
import requests

from .config import (
    BASE_URL,
    LOGIN_URL,
    TRAINER_DATA_URL,
    GAMESAVE_SLOT_URL,
    DEFAULT_HEADERS,
    SLOT_FETCH_PATHS,
    SLOT_UPDATE_PATHS,
    CLIENT_SESSION_ID,
)
from .token import to_urlsafe_b64, to_standard_b64


class PokerogueAPI:
    """Thin HTTP client for Pokerogue endpoints.

    Handles authentication and authenticated GET/POST calls for trainer and slot data.
    """

    def __init__(self, username: str, password: str, timeout: int = 15, max_retries: int = 3, backoff_factor: float = 0.5):
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.token: Optional[str] = None
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.client_session_id: Optional[str] = CLIENT_SESSION_ID

    # --- Auth ---
    def login(self) -> str:
        payload = {"username": self.username, "password": self.password}
        # First try form-encoded (observed in production)
        try:
            resp = self._request("post", LOGIN_URL, data=payload)
        except RuntimeError as e:
            msg = str(e)
            # Fallback: some deployments accept JSON body only
            if "Unauthorized" in msg or "HTTP 401" in msg:
                resp = self._request(
                    "post",
                    LOGIN_URL,
                    headers={**DEFAULT_HEADERS, "content-type": "application/json"},
                    json=payload,
                )
            else:
                raise
        data = self._json(resp)
        token = data.get("token")
        if not token:
            raise RuntimeError("Authentication succeeded but no token returned.")
        self.token = token
        # Capture clientSessionId if present
        self.client_session_id = data.get("clientSessionId", self.client_session_id)
        return token

    # --- Trainer ---
    def get_trainer(self) -> Dict[str, Any]:
        # Prefer system save when clientSessionId is available; otherwise fall back to account info
        if self.client_session_id:
            return self.get_system()
        resp = self._request("get", TRAINER_DATA_URL, headers=self._auth_headers())
        return self._json(resp)

    def get_account_info(self) -> Dict[str, Any]:
        resp = self._request("get", TRAINER_DATA_URL, headers=self._auth_headers())
        return self._json(resp)

    def update_trainer(self, trainer_data: Dict[str, Any]) -> Dict[str, Any]:
        # Align with server: system data update via savedata/system/update
        if self.client_session_id:
            return self.update_system(trainer_data)
        # Fallbacks retained for legacy behavior
        resp = self._request(
            "post",
            TRAINER_DATA_URL,
            headers=self._auth_headers(json_content=True),
            json=trainer_data,
        )
        return self._json(resp)

    # --- System (trainer-like persistent data) ---
    def get_system(self) -> Dict[str, Any]:
        if not self.client_session_id:
            raise RuntimeError("clientSessionId is required for system get. Set via env/--csid or .env")
        url = f"{BASE_URL}/savedata/system/get?clientSessionId={self.client_session_id}"
        resp = self._request("get", url, headers=self._auth_headers())
        return self._json(resp)

    def update_system(self, system_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client_session_id:
            raise RuntimeError("clientSessionId is required for system update. Set via env/--csid or .env")
        # Ensure session active by touching GET (server marks active if not)
        try:
            _ = self.get_system()
        except Exception:
            pass
        url = f"{BASE_URL}/savedata/system/update?clientSessionId={self.client_session_id}"
        resp = self._request(
            "post",
            url,
            headers=self._auth_headers(json_content=True),
            json=system_data,
        )
        # Server returns 204 No Content; coerce to empty dict for consistency
        try:
            return self._json(resp)
        except RuntimeError:
            return {}

    def system_verify(self) -> Dict[str, Any]:
        if not self.client_session_id:
            raise RuntimeError("clientSessionId is required for system verify. Set via env/--csid or .env")
        url = f"{BASE_URL}/savedata/system/verify?clientSessionId={self.client_session_id}"
        resp = self._request("get", url, headers=self._auth_headers())
        return self._json(resp)

    # --- Save Slots ---
    def get_slot(self, slot: int) -> Dict[str, Any]:
        # Canonical (browser) endpoint requires clientSessionId
        if not self.client_session_id:
            raise RuntimeError(
                "clientSessionId is required for slot fetch. Set ROGUEEDITOR_CLIENT_SESSION_ID, "
                "pass --csid to CLI, or add 'clientSessionId = <value>' to .env/env_data.txt"
            )
        # Prefer zero-based indexing server-side; UI uses 1-5
        zero = max(0, slot - 1)
        primary = f"{BASE_URL}/savedata/session/get?slot={zero}&clientSessionId={self.client_session_id}"
        try:
            resp = self._request("get", primary, headers=self._auth_headers())
            return self._json(resp)
        except RuntimeError as primary_err:
            errors: list[str] = [f"GET {primary} -> {primary_err}"]
            # Fallback to as-entered slot in case of deployment differences
            alt = f"{BASE_URL}/savedata/session/get?slot={slot}&clientSessionId={self.client_session_id}"
            try:
                resp = self._request("get", alt, headers=self._auth_headers())
                return self._json(resp)
            except RuntimeError as e2:
                errors.append(f"GET {alt} -> {e2}")
            # As a final fallback, iterate configured candidates (defensive)
            csid = self.client_session_id
            for idx in (slot, slot - 1):
                for tmpl in SLOT_FETCH_PATHS:
                    if "{csid}" in tmpl and not csid:
                        continue
                    path = tmpl.format(i=idx, csid=csid)
                    url = path if path.startswith("http") else f"{BASE_URL}{path}"
                    if url in (primary,):
                        continue
                    try:
                        resp = self._request("get", url, headers=self._auth_headers())
                        return self._json(resp)
                    except RuntimeError as e3:
                        errors.append(f"GET {url} -> {e3}")
            raise RuntimeError("All slot fetch endpoints failed: " + "; ".join(errors[-3:]))

    def update_slot(self, slot: int, save_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client_session_id:
            raise RuntimeError("clientSessionId is required for slot update. Set via env/--csid or .env")
        # Ensure session is marked active and not stale
        try:
            _ = self.get_slot(slot)
        except Exception:
            pass
        zero = max(0, slot - 1)
        headers = self._auth_headers(json_content=True)
        tried: set[str] = set()
        errors: list[str] = []
        candidates: list[str] = []
        # Primary canonical endpoints
        candidates.append(f"{BASE_URL}/savedata/session/update?slot={zero}&clientSessionId={self.client_session_id}")
        if slot != zero:
            candidates.append(f"{BASE_URL}/savedata/session/update?slot={slot}&clientSessionId={self.client_session_id}")
        # Alternative 'set' endpoints sometimes used in deployments
        candidates.append(f"{BASE_URL}/savedata/session/set?slot={zero}&clientSessionId={self.client_session_id}")
        if slot != zero:
            candidates.append(f"{BASE_URL}/savedata/session/set?slot={slot}&clientSessionId={self.client_session_id}")
        # Config-driven fallbacks
        csid = self.client_session_id
        for idx in (slot, slot - 1):
            for tmpl in SLOT_UPDATE_PATHS:
                if "{csid}" in tmpl and not csid:
                    continue
                path = tmpl.format(i=idx, csid=csid)
                url = path if path.startswith("http") else f"{BASE_URL}{path}"
                candidates.append(url)
        # Attempt in order, skipping duplicates
        for url in candidates:
            if url in tried:
                continue
            tried.add(url)
            try:
                resp = self._request("post", url, headers=headers, json=save_data)
                try:
                    return self._json(resp)
                except RuntimeError:
                    return {}
            except RuntimeError as e:
                errors.append(f"POST {url} -> {e}")
                continue
        raise RuntimeError("All slot update endpoints failed: " + "; ".join(errors[-3:]))

    # --- Core request with retry/backoff ---
    def _request(self, method: str, url: str, headers: Optional[Dict[str, str]] = None, data: Any = None, json: Any = None) -> requests.Response:
        attempt = 0
        last_exc: Optional[Exception] = None
        while attempt < self.max_retries:
            try:
                resp = self.session.request(method, url, headers=headers, data=data, json=json, timeout=self.timeout)
                # Retry on 429 or 5xx
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    delay = self._retry_after_delay(resp) or self._backoff(attempt)
                    attempt += 1
                    if attempt >= self.max_retries:
                        self._raise_for_status(resp)
                    time.sleep(delay)
                    continue
                # Non-retriable -> raise if error
                if 400 <= resp.status_code < 600:
                    self._raise_for_status(resp)
                return resp
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exc = e
                delay = self._backoff(attempt)
                attempt += 1
                if attempt >= self.max_retries:
                    raise
                time.sleep(delay)
        # Should not reach here; re-raise last exception just in case
        if last_exc:
            raise last_exc
        raise RuntimeError("Request failed without exception")

    def _backoff(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** attempt)

    @staticmethod
    def _retry_after_delay(resp: requests.Response) -> Optional[float]:
        ra = resp.headers.get("Retry-After")
        if not ra:
            return None
        try:
            return float(ra)
        except Exception:
            return None

    # --- Helpers ---
    def _auth_headers(self, json_content: bool = False) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError("Not authenticated. Call login() first.")
        # Prefer standard Base64; some servers reject URL-safe in Authorization
        token = to_standard_b64(self.token)
        headers = {
            **DEFAULT_HEADERS,
            # Server expects raw token without 'Bearer ' prefix
            "authorization": token,
        }
        if json_content:
            headers["content-type"] = "application/json"
        return headers

    def _auth_headers_raw(self, json_content: bool = False) -> Dict[str, str]:
        if not self.token:
            raise RuntimeError("Not authenticated. Call login() first.")
        headers = {
            **DEFAULT_HEADERS,
            "authorization": self.token,
        }
        if json_content:
            headers["content-type"] = "application/json"
        return headers

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code == 404:
            raise RuntimeError("Endpoint not found (404)")
        if resp.status_code == 401:
            body = (resp.text or "").strip()
            snippet = body[:200] + ("..." if len(body) > 200 else "")
            raise RuntimeError(f"Unauthorized (401): {snippet}")
        if resp.status_code == 403:
            raise RuntimeError("Forbidden (403)")
        if 400 <= resp.status_code < 600:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

    @staticmethod
    def _json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Invalid JSON response. Content-Type: {resp.headers.get('content-type')}"
            )
