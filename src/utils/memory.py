"""Simple in-memory session storage for the bill splitting agent."""

import json
from typing import Any


_MEMORY_DB: dict[str, str] = {}


def save_memory(key: str, data: Any, user_id: str = "default") -> bool:
    memory_key = f"{key}_{user_id}"
    _MEMORY_DB[memory_key] = json.dumps(data, default=str)
    return True


def load_memory(key: str, user_id: str = "default") -> Any | None:
    memory_key = f"{key}_{user_id}"
    raw = _MEMORY_DB.get(memory_key)
    if raw is None:
        return None
    return json.loads(raw)


def search_memory(query: str, user_id: str = "default", limit: int = 10) -> dict[str, Any]:
    matches = [key for key in _MEMORY_DB if query in key and key.endswith(f"_{user_id}")]
    return {
        "query": query,
        "user_id": user_id,
        "total_found": len(matches),
        "results": matches[:limit],
    }


def get_memory_stats() -> dict[str, Any]:
    return {
        "total_keys": len(_MEMORY_DB),
        "keys": sorted(_MEMORY_DB),
        "total_size": sum(len(value) for value in _MEMORY_DB.values()),
    }

