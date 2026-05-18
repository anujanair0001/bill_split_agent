"""Persistent storage for saved bills."""

from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BILLS_FILE = DATA_DIR / "saved_bills.json"


def list_saved_bills() -> list[dict[str, Any]]:
    bills = _read_bills()
    return sorted(bills, key=lambda bill: bill.get("updated_at", ""), reverse=True)


def get_saved_bill(bill_id: str) -> dict[str, Any] | None:
    for bill in _read_bills():
        if bill.get("id") == bill_id:
            return bill
    return None


def save_bill_record(record: dict[str, Any]) -> dict[str, Any]:
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
