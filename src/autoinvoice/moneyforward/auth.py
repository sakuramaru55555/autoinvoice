"""MoneyForward Cloud Invoice OAuth 2.0 authentication flow."""

from __future__ import annotations

import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://api.biz.moneyforward.com/authorize"
TOKEN_URL = "https://api.biz.moneyforward.com/token"
SCOPES = "mfc/invoice/data.read mfc/invoice/data.write"


class MFOAuthManager:
    """Manages OAuth 2.0 tokens for MoneyForward Cloud Invoice API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_path: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_path = Path(token_path)
        self._tokens: dict[str, Any] | None = None
        self._state: str = ""

        self._load_tokens()

    # --- Public Interface ---

    def authorize(self) -> str:
        """Generate the authorization URL for the user to visit."""
        self._state = secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": self._state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def start_callback_server(self) -> dict:
        """Start a local HTTP server to receive the OAuth callback.

        Returns the token dict on success.
        """
        parsed = urlparse(self.redirect_uri)
        port = parsed.port or 38080
        auth_code_holder: dict[str, str | None] = {"code": None, "error": None}

        outer = self  # Capture for inner class

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)

                # Validate state
                state = query.get("state", [None])[0]
                if state != outer._state:
                    auth_code_holder["error"] = "Invalid state parameter"
                    self._respond("認証エラー: state パラメータが一致しません")
                    return

                error = query.get("error", [None])[0]
                if error:
                    auth_code_holder["error"] = error
                    self._respond(f"認証エラー: {error}")
                    return

                code = query.get("code", [None])[0]
                if code:
                    auth_code_holder["code"] = code
                    self._respond(
                        "認証が完了しました！このページを閉じてください。"
                    )
                else:
                    auth_code_holder["error"] = "No authorization code received"
                    self._respond("認証エラー: コードを受け取れませんでした")

            def _respond(self, message: str):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AutoInvoice</title></head>
<body style="text-align:center;padding:50px;font-family:sans-serif;">
<h2>{message}</h2></body></html>"""
                self.wfile.write(html.encode("utf-8"))

            def log_message(self, format, *args):
                pass  # Suppress default logging

        server = HTTPServer(("localhost", port), CallbackHandler)
        server.timeout = 120  # 2 minute timeout

        # Open browser
        auth_url = self.authorize()
        webbrowser.open(auth_url)

        # Wait for callback
        server.handle_request()
        server.server_close()

        if auth_code_holder["error"]:
            raise RuntimeError(
                f"OAuth認証エラー: {auth_code_holder['error']}"
            )
        if not auth_code_holder["code"]:
            raise RuntimeError("認証コードを受け取れませんでした（タイムアウト）")

        return self.handle_callback(auth_code_holder["code"])

    def handle_callback(self, auth_code: str) -> dict:
        """Exchange authorization code for tokens."""
        # Use client_secret_post (NOT client_secret_basic)
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        resp = requests.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        tokens = resp.json()

        # Add expiry timestamp
        if "expires_in" in tokens:
            tokens["expires_at"] = time.time() + tokens["expires_in"]

        self._tokens = tokens
        self._save_tokens()
        return tokens

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._tokens is None:
            raise RuntimeError(
                "認証されていません。先に 'autoinvoice auth' を実行してください。"
            )

        # Check if token is expired (with 60-second buffer)
        expires_at = self._tokens.get("expires_at", 0)
        if time.time() > expires_at - 60:
            self._refresh_token()

        return self._tokens["access_token"]

    # --- Private Methods ---

    def _refresh_token(self) -> None:
        """Refresh the access token using the refresh token."""
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(
                "リフレッシュトークンがありません。'autoinvoice auth' を再実行してください。"
            )

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        resp = requests.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        new_tokens = resp.json()

        if "expires_in" in new_tokens:
            new_tokens["expires_at"] = time.time() + new_tokens["expires_in"]

        # Preserve refresh_token if not returned in response
        if "refresh_token" not in new_tokens and refresh_token:
            new_tokens["refresh_token"] = refresh_token

        self._tokens = new_tokens
        self._save_tokens()

    def _load_tokens(self) -> None:
        """Load tokens from disk."""
        if self.token_path.exists():
            with open(self.token_path, encoding="utf-8") as f:
                self._tokens = json.load(f)

    def _save_tokens(self) -> None:
        """Save tokens to disk."""
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(self._tokens, f, indent=2, ensure_ascii=False)
