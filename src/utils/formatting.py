"""Output formatting helpers."""

from decimal import Decimal
from typing import Any


def money(value: Decimal | str | float | int) -> str:
    return f"{Decimal(str(value)):.2f}"


def format_split_summary(plan: dict[str, Any]) -> str:
    lines = [
        "=" * 56,
        "BILLSPLIT AGENT RESULT",
        "=" * 56,
        f"Restaurant: {plan.get('restaurant_name') or 'Unknown'}",
        f"Detected total: {money(plan['detected_total'])}",
        "",
        "Who pays what:",
    ]

    for person in plan["splits"]:
        lines.append(
            f"- {person['person']}: {money(person['total'])} "
            f"(items {money(person['item_subtotal'])}, "
            f"service {money(person['service_charge'])}, tax {money(person['tax'])})"
        )
        for item in person["items"]:
            lines.append(f"  * {item['name']}: {money(item['amount'])}")

    if plan.get("recommendations"):
        lines.extend(["", "Notes:"])
        lines.extend(f"- {note}" for note in plan["recommendations"])

    lines.append("=" * 56)
    return "\n".join(lines)

