"""Supabase persistence for saved bills and receipt files."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import functools
import os
from typing import Any
from urllib.parse import quote

import requests


DEFAULT_TABLE = "saved_bills"
DEFAULT_BUCKET = "receipts"
DEFAULT_SETTINGS_TABLE = "app_settings"
TEAM_MEMBERS_KEY = "team_members"


class SupabaseError(Exception):
    """Raised when a Supabase API request fails."""
    pass


def set_db_error(error: Exception) -> None:
    try:
        import streamlit as st
        st.session_state["supabase_error"] = str(error)
    except Exception:
        pass


def clear_db_error() -> None:
    try:
        import streamlit as st
        if "supabase_error" in st.session_state:
            del st.session_state["supabase_error"]
    except Exception:
        pass


def handle_request_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            clear_db_error()
            return result
        except requests.RequestException as e:
            err = SupabaseError(f"Supabase request failed: {e}")
            set_db_error(err)
            raise err from e
    return wrapper


def is_configured() -> bool:
    config = _config()
    return bool(config["url"] and config["key"])


@handle_request_errors
def list_saved_bills() -> list[dict[str, Any]]:
    response = requests.get(
        _rest_url(),
        headers=_headers(),
        params={"select": "*", "order": "updated_at.desc"},
        timeout=20,
    )
    response.raise_for_status()
    return [_row_to_record(row) for row in response.json()]


@handle_request_errors
def get_saved_bill(bill_id: str) -> dict[str, Any] | None:
    response = requests.get(
        _rest_url(),
        headers=_headers(),
        params={"id": f"eq.{bill_id}", "select": "*", "limit": "1"},
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return _row_to_record(rows[0]) if rows else None


@handle_request_errors
def save_bill_record(record: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    saved = {
        **record,
        "created_at": record.get("created_at") or now,
        "updated_at": now,
    }
    row = {
        "id": saved["id"],
        "restaurant_name": saved.get("restaurant_name") or "Unknown restaurant",
        "payload": _to_jsonable(saved),
        "receipt_file_path": saved.get("receipt_file_path"),
        "receipt_file_name": saved.get("receipt_file_name"),
        "receipt_file_type": saved.get("receipt_file_type"),
        "created_at": saved["created_at"],
        "updated_at": saved["updated_at"],
    }
    response = requests.post(
        _rest_url(),
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
        params={"on_conflict": "id"},
        json=row,
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return _row_to_record(rows[0]) if rows else saved


@handle_request_errors
def upload_receipt_file(bill_id: str, upload: dict[str, Any]) -> dict[str, str]:
    file_name = upload.get("name") or "receipt"
    file_type = upload.get("type") or "application/octet-stream"
    file_bytes = upload.get("bytes") or b""
    extension = _extension(file_name)
    path = f"{bill_id}/receipt{extension}"

    response = requests.post(
        f"{_storage_object_url()}/{_quote_path(path)}",
        headers={
            **_headers(),
            "Content-Type": file_type,
            "cache-control": "3600",
            "x-upsert": "true",
        },
        data=file_bytes,
        timeout=60,
    )
    response.raise_for_status()
    return {
        "receipt_file_path": path,
        "receipt_file_name": file_name,
        "receipt_file_type": file_type,
    }


@handle_request_errors
def download_receipt_file(path: str) -> bytes | None:
    response = requests.get(
        f"{_storage_object_url()}/{_quote_path(path)}",
        headers=_headers(),
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


@handle_request_errors
def load_team_members() -> list[str] | None:
    response = requests.get(
        _settings_url(),
        headers=_headers(),
        params={"key": f"eq.{TEAM_MEMBERS_KEY}", "select": "value", "limit": "1"},
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    if not rows:
        return None
    value = rows[0].get("value")
    return value if isinstance(value, list) else None


@handle_request_errors
def save_team_members(members: list[str]) -> list[str]:
    response = requests.post(
        _settings_url(),
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
        params={"on_conflict": "key"},
        json={"key": TEAM_MEMBERS_KEY, "value": members},
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    value = rows[0].get("value") if rows else members
    return value if isinstance(value, list) else members


def _row_to_record(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    return {
        **payload,
        "id": row.get("id") or payload.get("id"),
        "restaurant_name": row.get("restaurant_name") or payload.get("restaurant_name"),
        "receipt_file_path": row.get("receipt_file_path") or payload.get("receipt_file_path"),
        "receipt_file_name": row.get("receipt_file_name") or payload.get("receipt_file_name"),
        "receipt_file_type": row.get("receipt_file_type") or payload.get("receipt_file_type"),
        "created_at": row.get("created_at") or payload.get("created_at"),
        "updated_at": row.get("updated_at") or payload.get("updated_at"),
    }


def _config() -> dict[str, str]:
    return {
        "url": _setting("SUPABASE_URL"),
        "key": _setting("SUPABASE_SERVICE_KEY") or _setting("SUPABASE_KEY"),
        "table": _setting("SUPABASE_BILLS_TABLE") or DEFAULT_TABLE,
        "settings_table": _setting("SUPABASE_SETTINGS_TABLE") or DEFAULT_SETTINGS_TABLE,
        "bucket": _setting("SUPABASE_RECEIPTS_BUCKET") or DEFAULT_BUCKET,
    }


def _setting(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        return str(st.secrets.get(name, ""))
    except Exception:
        return ""


def _headers() -> dict[str, str]:
    key = _config()["key"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _rest_url() -> str:
    config = _config()
    return f"{config['url'].rstrip('/')}/rest/v1/{config['table']}"


def _storage_object_url() -> str:
    config = _config()
    return f"{config['url'].rstrip('/')}/storage/v1/object/{config['bucket']}"


def _settings_url() -> str:
    config = _config()
    return f"{config['url'].rstrip('/')}/rest/v1/{config['settings_table']}"


def _quote_path(path: str) -> str:
    return "/".join(quote(part) for part in path.split("/"))


def _extension(file_name: str) -> str:
    if "." not in file_name:
        return ""
    return "." + file_name.rsplit(".", 1)[-1].lower()


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value
