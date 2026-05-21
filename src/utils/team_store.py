"""Persistent storage for saved team members."""

import json
from pathlib import Path

from . import supabase_store


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TEAM_FILE = DATA_DIR / "team_members.json"
DEFAULT_TEAM = ["Person 1", "Person 2"]


def load_team_members() -> list[str]:
    if supabase_store.is_configured():
        members = supabase_store.load_team_members()
        if members:
            return _clean_names(members) or DEFAULT_TEAM[:]
    if not TEAM_FILE.exists():
        return DEFAULT_TEAM[:]

    try:
        data = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_TEAM[:]

    if not isinstance(data, list):
        return DEFAULT_TEAM[:]

    members = _clean_names(str(value) for value in data)
    return members or DEFAULT_TEAM[:]


def save_team_members(members: list[str]) -> list[str]:
    cleaned = _clean_names(members)
    if supabase_store.is_configured():
        return _clean_names(supabase_store.save_team_members(cleaned)) or DEFAULT_TEAM[:]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEAM_FILE.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    return cleaned


def _clean_names(values) -> list[str]:
    cleaned = []
    for value in values:
        name = " ".join(str(value).split())
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned
