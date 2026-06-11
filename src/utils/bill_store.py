"""Persistent storage for saved bills."""

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import supabase_store


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BILLS_FILE = DATA_DIR / "saved_bills.json"


def list_saved_bills() -> list[dict[str, Any]]:
    if supabase_store.is_configured():
        try:
            return supabase_store.list_saved_bills()
        except supabase_store.SupabaseError:
            pass
    bills = _read_bills()
    return sorted(bills, key=lambda bill: bill.get("updated_at", ""), reverse=True)


def get_saved_bill(bill_id: str) -> dict[str, Any] | None:
    if supabase_store.is_configured():
        try:
            return supabase_store.get_saved_bill(bill_id)
        except supabase_store.SupabaseError:
            pass
    for bill in _read_bills():
        if bill.get("id") == bill_id:
            return bill
    return None


def save_bill_record(record: dict[str, Any]) -> dict[str, Any]:
    if supabase_store.is_configured():
        try:
            bill_id = record.get("id") or uuid4().hex
            return supabase_store.save_bill_record({**record, "id": bill_id})
        except supabase_store.SupabaseError:
            pass
    bills = _read_bills()
    now = datetime.now().isoformat(timespec="seconds")
    bill_id = record.get("id") or uuid4().hex
    saved = {
        **record,
        "id": bill_id,
        "created_at": record.get("created_at") or now,
        "updated_at": now,
    }

    replaced = False
    for index, bill in enumerate(bills):
        if bill.get("id") == bill_id:
            bills[index] = saved
            replaced = True
            break
    if not replaced:
        bills.append(saved)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BILLS_FILE.write_text(json.dumps(_to_jsonable(bills), indent=2), encoding="utf-8")
    return saved


def save_receipt_upload(bill_id: str, upload: dict[str, Any] | None) -> dict[str, str]:
    if not upload or not supabase_store.is_configured():
        return {}
    try:
        return supabase_store.upload_receipt_file(bill_id, upload)
    except supabase_store.SupabaseError:
        return {}


def load_receipt_upload(saved: dict[str, Any]) -> dict[str, Any] | None:
    path = saved.get("receipt_file_path")
    if not path or not supabase_store.is_configured():
        return None
    try:
        file_bytes = supabase_store.download_receipt_file(path)
        if file_bytes is not None:
            return {
                "name": saved.get("receipt_file_name") or "receipt",
                "type": saved.get("receipt_file_type") or "application/octet-stream",
                "bytes": file_bytes,
            }
    except supabase_store.SupabaseError:
        pass
    return None


def _read_bills() -> list[dict[str, Any]]:
    if not BILLS_FILE.exists():
        return []
    try:
        data = json.loads(BILLS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


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
