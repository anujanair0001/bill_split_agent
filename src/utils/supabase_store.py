"""Supabase persistence for saved bills and receipt files."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import os
from typing import Any
from urllib.parse import quote

import requests


DEFAULT_TABLE = "saved_bills"
DEFAULT_BUCKET = "receipts"


def is_configured() -> bool:
    config = _config()
    return bool(config["url"] and config["key"])


def list_saved_bills() -> list[dict[str, Any]]:
    response = requests.get(
        _rest_url(),
        headers=_headers(),
        params={"select": "*", "order": "updated_at.desc"},
        timeout=20,
    )
    response.raise_for_status()
    return [_row_to_record(row) for row in response.json()]


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
