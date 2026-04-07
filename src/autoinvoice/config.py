"""Configuration loader with YAML parsing and environment variable interpolation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml


_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _interpolate_env(value: Any) -> Any:
    """Replace ${VAR_NAME} placeholders with environment variable values.

    Missing env vars are kept as-is (deferred error at access time).
    """
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            # Keep placeholder; will error when actually accessed
            return match.group(0)
        return env_val

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _interpolate_recursive(data: Any) -> Any:
    """Recursively interpolate environment variables in config data."""
    if isinstance(data, dict):
        return {k: _interpolate_recursive(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_interpolate_recursive(item) for item in data]
    return _interpolate_env(data)


def _resolve_path(base_dir: Path, path_str: str) -> str:
    """Resolve a relative path against the config file's directory."""
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str(base_dir / p)


class Config:
    """Application configuration loaded from YAML file."""

    def __init__(self, data: dict, base_dir: Path):
        self._data = data
        self._base_dir = base_dir

    # --- Google Sheets ---

    @property
    def spreadsheet_id(self) -> str:
        return self._data["google_sheets"]["spreadsheet_id"]

    @property
    def worksheet_gid(self) -> int:
        return self._data["google_sheets"]["worksheet_gid"]

    @property
    def service_account_path(self) -> str:
        return _resolve_path(
            self._base_dir,
            self._data["google_sheets"]["service_account_path"],
        )

    # --- MoneyForward ---

    @property
    def mf_client_id(self) -> str:
        return self._data["moneyforward"]["client_id"]

    @property
    def mf_client_secret(self) -> str:
        return self._data["moneyforward"]["client_secret"]

    @property
    def mf_redirect_uri(self) -> str:
        return self._data["moneyforward"]["redirect_uri"]

    @property
    def mf_token_path(self) -> str:
        return _resolve_path(
            self._base_dir,
            self._data["moneyforward"]["token_path"],
        )

    # --- Invoice ---

    @property
    def partner_name(self) -> str:
        return self._data["invoice"]["partner_name"]

    @property
    def department_name(self) -> str:
        return self._data["invoice"]["department_name"]

    @property
    def title_template(self) -> str:
        return self._data["invoice"]["title_template"]

    @property
    def payment_condition(self) -> str:
        return self._data["invoice"].get("payment_condition", "銀行振込")

    @property
    def invoice_note(self) -> str:
        return self._data["invoice"].get("note", "")

    # --- SendGrid ---

    @property
    def sendgrid_api_key(self) -> str:
        return self._data.get("sendgrid", {}).get("api_key", "")

    @property
    def sendgrid_from_email(self) -> str:
        return self._data.get("sendgrid", {}).get("from_email", "")

    # --- Trigger ---

    @property
    def gmail_query(self) -> str:
        return self._data.get("trigger", {}).get(
            "gmail_query",
            "from:hasegawa.s@tseminar.co.jp subject:月分給与 after:2026/03/31",
        )

    @property
    def spreadsheet_id_check(self) -> str:
        return self._data.get("trigger", {}).get(
            "spreadsheet_id_check", self.spreadsheet_id
        )

    @property
    def processed_path(self) -> str:
        raw = self._data.get("trigger", {}).get(
            "processed_path", "credentials/processed_emails.json"
        )
        return _resolve_path(self._base_dir, raw)

    # --- Mail ---

    @property
    def mail_to(self) -> str:
        return self._data["mail"]["to"]

    @property
    def mail_cc(self) -> str:
        return self._data["mail"]["cc"]

    @property
    def mail_subject_template(self) -> str:
        return self._data["mail"]["subject_template"]

    @property
    def mail_body_template(self) -> str:
        return self._data["mail"]["body_template"]


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file.

    Search order (if config_path is None):
      1. ./config.yaml
      2. ~/.autoinvoice/config.yaml
    """
    if config_path:
        path = Path(config_path)
    else:
        candidates = [
            Path.cwd() / "config.yaml",
            Path.home() / ".autoinvoice" / "config.yaml",
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            raise FileNotFoundError(
                "config.yaml が見つかりません。\n"
                "config.example.yaml をコピーして config.yaml を作成してください:\n"
                "  cp config.example.yaml config.yaml"
            )

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    data = _interpolate_recursive(raw)
    return Config(data, path.parent)
