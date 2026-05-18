"""Core bill parsing and splitting tools."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any
from uuid import uuid4

from src.utils.memory import load_memory, save_memory


CENT = Decimal("0.01")
MONEY_PATTERN = re.compile(r"(?:RM|\$)?\s*(?P<amount>\d{1,6}[.,]\d{2})\s*$", re.IGNORECASE)
OCR_MONEY_PATTERN = re.compile(
    r"(?P<prefix>R?M|AM|\$)?\s*(?P<whole>\d{1,6})(?:(?P<sep>[.,])\s*|\s+)(?P<cents>\d{2})\s*$",
    re.IGNORECASE,
)
COMPACT_RM_PATTERN = re.compile(r"\bR?M\s*(?P<digits>\d{3})\s*$", re.IGNORECASE)
SERVICE_WORDS = ("service", "svc", "service charge")
TAX_WORDS = ("tax", "sst", "gst", "vat")
NOISE_WORDS = (
    "subtotal", "total", "grand total", "cash", "change", "visa", "mastercard",
    "rounding", "duitnow", "approved", "thank you", "customer copy", "tip",
)
METADATA_WORDS = (
    "table", "pax", "qty", "invoice", "receipt", "date", "time", "tel", "phone",
    "address", "staff", "counter", "batch", "appr", "trace", "customers",
    "customer", "terminal", "merchant", "gst id", "sst id", "st id", "tax id",
    "company", "sdn bhd", "scan qr", "e-invoice", "e-involce",
)
RESTAURANT_HINTS = ("restaurant", "cafe", "coffee", "kitchen", "bistro", "bar", "din tai", "thai", "sushi")


@dataclass(frozen=True)
class BillItem:
    id: str
    name: str
    price: Decimal


@dataclass(frozen=True)
class Bill:
    restaurant_name: str
    items: list[BillItem]
    service_charge: Decimal
    tax: Decimal
    raw_text: str
    receipt_subtotal: Decimal | None = None
    receipt_total: Decimal | None = None

    @property
    def detected_total(self) -> Decimal:
        item_total = sum((item.price for item in self.items), Decimal("0"))
        return (item_total + self.service_charge + self.tax).quantize(CENT)

    @property
    def bill_total(self) -> Decimal:
        return self.receipt_total if self.receipt_total is not None else self.detected_total


def parse_bill_text(text: str, context: Any | None = None) -> dict[str, Any]:
    """Parse receipt text into structured bill data."""
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    restaurant_name = _guess_restaurant_name(lines)
    items: list[BillItem] = []
    service_charge = Decimal("0")
    tax = Decimal("0")
    receipt_subtotal: Decimal | None = None
    receipt_total: Decimal | None = None
    pending_item_label: str | None = None

    for index, line in enumerate(lines):
        addon = _parse_inline_addon_line(line)
        if addon is not None:
            name, amount = addon
            items.append(BillItem(id=str(uuid4()), name=name, price=amount))
            pending_item_label = None
            continue

        parsed = _parse_money_line(line)
        if parsed is None:
            summary = _parse_standalone_summary_amount(lines, index)
            if summary:
                kind, amount = summary
                if kind == "subtotal":
                    receipt_subtotal = amount
                elif kind == "charge":
                    service_charge += amount
                elif kind == "total":
                    receipt_total = amount
            elif _looks_like_pending_item_label(line):
                pending_item_label = _clean_item_label(line)
            continue

        label, amount = parsed
        if _is_quantity_only_label(label) and pending_item_label:
            label = pending_item_label
            pending_item_label = None
        elif _is_quantity_only_label(label):
            label = "Unclear OCR item"
        lowered = label.lower()
        if _is_subtotal_label(lowered):
            receipt_subtotal = amount
        elif _is_total_label(lowered):
            receipt_total = amount
        elif _contains_any(lowered, SERVICE_WORDS):
            service_charge += amount
        elif _contains_any(lowered, TAX_WORDS):
            service_charge += amount
        elif _contains_any(lowered, NOISE_WORDS):
            continue
        elif label and not _looks_like_metadata(label):
            items.append(BillItem(id=str(uuid4()), name=label, price=amount))
            pending_item_label = None

    inferred_subtotal, inferred_charge, inferred_total = _infer_summary_amounts(lines, receipt_total)
    if receipt_subtotal is None:
        receipt_subtotal = inferred_subtotal
    if receipt_total is None:
        receipt_total = inferred_total
    if service_charge == 0 and inferred_charge is not None:
        service_charge = inferred_charge

    bill = Bill(
        restaurant_name=restaurant_name,
        items=items,
        service_charge=service_charge.quantize(CENT),
        tax=tax.quantize(CENT),
        raw_text=text,
        receipt_subtotal=receipt_subtotal,
        receipt_total=receipt_total,
    )
    result = _bill_to_dict(bill)
    save_memory("last_bill", result, _user_id(context))
    return result


def remember_split_preferences(people: list[str], context: Any | None = None) -> dict[str, Any]:
    """Remember the latest dining group for the current user."""
    cleaned = [_clean_person(person) for person in people if _clean_person(person)]
    result = {"people": cleaned, "count": len(cleaned)}
    save_memory("recent_people", result, _user_id(context))
    return result


def assign_items_from_note(
    bill: dict[str, Any],
    people: list[str],
    assignment_note: str = "",
    context: Any | None = None,
) -> dict[str, list[str]]:
    """Infer item assignments from simple natural language notes."""
    cleaned_people = [_clean_person(person) for person in people if _clean_person(person)]
    if not cleaned_people:
        recent = load_memory("recent_people", _user_id(context)) or {}
        cleaned_people = recent.get("people", [])
    if not cleaned_people:
        raise ValueError("At least one person is required.")

    clauses = _assignment_clauses(assignment_note)
    assignments: dict[str, list[str]] = {}

    for item in bill["items"]:
        item_name = item["name"]
        item_lower = item_name.lower()
        eaters: list[str] = []

        for clause in clauses:
            if item_lower not in clause:
                continue
            if _shared_phrase_found(clause):
                eaters = cleaned_people[:]
                break
            eaters.extend(person for person in cleaned_people if person.lower() in clause)

        assignments[item["id"]] = eaters or cleaned_people[:]

    save_memory("last_assignments", assignments, _user_id(context))
    return assignments


def calculate_bill_split(
    bill: dict[str, Any],
    people: list[str],
    assignments: dict[str, list[str] | dict[str, Any]],
    context: Any | None = None,
) -> dict[str, Any]:
    """Calculate each person's total with proportional service and tax."""
    cleaned_people = [_clean_person(person) for person in people if _clean_person(person)]
    if not cleaned_people:
        raise ValueError("At least one person is required.")

    item_lines = {person: [] for person in cleaned_people}
    item_totals = {person: Decimal("0") for person in cleaned_people}

    for item in bill["items"]:
        price = Decimal(str(item["price"]))
        portions = _normalize_item_portions(assignments.get(item["id"], []), item_totals)
        if not portions:
            continue

        for person, share in _split_by_portions(price, portions).items():
            item_totals[person] += share
            item_lines[person].append({"name": item["name"], "amount": share, "portions": portions[person]})

    subtotal = sum(item_totals.values(), Decimal("0"))
    service_parts = _split_proportionally(Decimal(str(bill["service_charge"])), item_totals, subtotal)
    tax_parts = _split_proportionally(Decimal(str(bill["tax"])), item_totals, subtotal)

    splits = []
    for person in cleaned_people:
        item_subtotal = item_totals[person].quantize(CENT)
        service_charge = service_parts[person]
        tax = tax_parts[person]
        total = (item_subtotal + service_charge + tax).quantize(CENT)
        splits.append(
            {
                "person": person,
                "items": item_lines[person],
                "item_subtotal": item_subtotal,
                "service_charge": service_charge,
                "tax": tax,
                "total": total,
            }
        )

    plan = {
        "restaurant_name": bill["restaurant_name"],
        "detected_total": Decimal(str(bill.get("bill_total", bill["detected_total"]))),
        "calculated_total": Decimal(str(bill["detected_total"])),
        "receipt_total": Decimal(str(bill["receipt_total"])) if bill.get("receipt_total") is not None else None,
        "receipt_subtotal": Decimal(str(bill["receipt_subtotal"])) if bill.get("receipt_subtotal") is not None else None,
        "people": cleaned_people,
        "splits": splits,
        "recommendations": _recommendations(bill, assignments),
    }
    save_memory("last_split", plan, _user_id(context))
    return plan


def _bill_to_dict(bill: Bill) -> dict[str, Any]:
    return {
        "restaurant_name": bill.restaurant_name,
        "items": [{"id": item.id, "name": item.name, "price": item.price} for item in bill.items],
        "service_charge": bill.service_charge,
        "tax": bill.tax,
        "detected_total": bill.detected_total,
        "bill_total": bill.bill_total,
        "receipt_subtotal": bill.receipt_subtotal,
        "receipt_total": bill.receipt_total,
        "validation": _validate_bill_totals(bill),
        "raw_text": bill.raw_text,
    }


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" .:-\t")


def _guess_restaurant_name(lines: list[str]) -> str:
    candidates = []
    for index, line in enumerate(lines[:14]):
        lowered = line.lower()
        if MONEY_PATTERN.search(line) or _contains_any(lowered, NOISE_WORDS + SERVICE_WORDS + TAX_WORDS + METADATA_WORDS):
            continue
        if _looks_like_address_or_code(line):
            continue
        if len(line) >= 3:
            score = 20 - index
            if _contains_any(lowered, RESTAURANT_HINTS):
                score += 30
            if any(char.isalpha() for char in line) and not re.search(r"\d{3,}", line):
                score += 5
            candidates.append((score, _cleanup_restaurant_name(line)))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return ""


def _parse_money_line(line: str) -> tuple[str, Decimal] | None:
    match = MONEY_PATTERN.search(line) or OCR_MONEY_PATTERN.search(line) or COMPACT_RM_PATTERN.search(line)
    if not match:
        return None
    label = _clean_item_label(line[: match.start()].strip(" .:-\t"))
    if not label:
        return None
    return label, _amount_from_money_match(match)


def _parse_standalone_summary_amount(lines: list[str], index: int) -> tuple[str, Decimal] | None:
    line = lines[index]
    amount = _parse_amount_only(line)
    if amount is None:
        return None

    previous_text = " ".join(lines[max(0, index - 3):index]).lower()
    if "grand total" in previous_text or re.search(r"\btotal\b", previous_text):
        return "total", amount
    if "subtotal" in previous_text or "sub total" in previous_text:
        return "subtotal", amount

    previous_amounts = [
        _parse_amount_only(previous)
        for previous in lines[max(0, index - 3):index]
    ]
    previous_amounts = [value for value in previous_amounts if value is not None]
    if previous_amounts:
        return "charge", amount

    return None


def _parse_amount_only(line: str) -> Decimal | None:
    normalized = line.strip()
    match = re.fullmatch(r"-?\s*(?:R?M|AM|\$)?\s*(\d{1,6})(?:[.,]\s*|\s+)(\d{2})", normalized, re.IGNORECASE)
    if not match:
        compact = re.fullmatch(r"-?\s*R?M\s*(\d{3})", normalized, re.IGNORECASE)
        if not compact:
            return None
        digits = compact.group(1)
        amount = Decimal(f"{digits[:-2]}.{digits[-2:]}").quantize(CENT)
        return -amount if normalized.startswith("-") else amount
    amount = Decimal(f"{match.group(1)}.{match.group(2)}").quantize(CENT)
    return -amount if normalized.startswith("-") else amount


def _infer_summary_amounts(lines: list[str], receipt_total: Decimal | None) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    amount_lines = []
    for index, line in enumerate(lines[-35:]):
        amount = _parse_amount_only(line)
        if amount is not None:
            amount_lines.append((index, amount))

    if not amount_lines:
        return None, None, receipt_total

    inferred_total = receipt_total or _infer_total_from_amount_lines(lines, amount_lines)
    inferred_subtotal = None
    inferred_charge = None

    if inferred_total is not None:
        subtotal_candidates = [
            amount
            for _, amount in amount_lines
            if amount > 0 and amount < inferred_total and amount >= inferred_total * Decimal("0.50")
        ]
        if subtotal_candidates:
            inferred_subtotal = max(subtotal_candidates)
            difference = (inferred_total - inferred_subtotal).quantize(CENT)
            if difference > 0:
                charge_candidates = [
                    amount
                    for _, amount in amount_lines
                    if amount > 0 and abs(amount - difference) <= Decimal("0.10")
                ]
                inferred_charge = charge_candidates[0] if charge_candidates else difference

    return inferred_subtotal, inferred_charge, inferred_total


def _infer_total_from_amount_lines(lines: list[str], amount_lines: list[tuple[int, Decimal]]) -> Decimal | None:
    trailing_text = " ".join(lines[-12:]).lower()
    positive_amounts = [amount for _, amount in amount_lines if amount > 0]
    if not positive_amounts:
        return None
    if "grand total" in trailing_text or re.search(r"\btotal\b", trailing_text):
        return positive_amounts[-1]
    return max(positive_amounts)


def _is_subtotal_label(label: str) -> bool:
    return bool(re.search(r"\bsub\s*total\b|\bsubtotal\b", label))


def _is_total_label(label: str) -> bool:
    return "grand total" in label or bool(re.fullmatch(r".*\btotal\b.*", label)) and not _is_subtotal_label(label)


def _validate_bill_totals(bill: Bill) -> dict[str, Any]:
    item_subtotal = sum((item.price for item in bill.items), Decimal("0")).quantize(CENT)
    calculated_total = bill.detected_total
    expected_subtotal = bill.receipt_subtotal
    expected_total = bill.receipt_total
    subtotal_difference = (item_subtotal - expected_subtotal).quantize(CENT) if expected_subtotal is not None else None
    total_difference = (calculated_total - expected_total).quantize(CENT) if expected_total is not None else None

    warnings = []
    if subtotal_difference is not None and abs(subtotal_difference) >= Decimal("0.02"):
        warnings.append(
            f"Extracted items sum to {item_subtotal}, but receipt subtotal is {expected_subtotal}. Difference: {subtotal_difference}."
        )
    if total_difference is not None and abs(total_difference) >= Decimal("0.02"):
        warnings.append(
            f"Calculated total is {calculated_total}, but receipt total is {expected_total}. Difference: {total_difference}."
        )

    return {
        "item_subtotal": item_subtotal,
        "calculated_total": calculated_total,
        "receipt_subtotal": expected_subtotal,
        "receipt_total": expected_total,
        "subtotal_difference": subtotal_difference,
        "total_difference": total_difference,
        "warnings": warnings,
    }


def _contains_any(value: str, words: tuple[str, ...]) -> bool:
    return any(word in value for word in words)


def _looks_like_metadata(label: str) -> bool:
    lowered = label.lower()
    return bool(
        _contains_any(lowered, METADATA_WORDS)
        or _contains_any(lowered, NOISE_WORDS)
        or _looks_like_address_or_code(label)
        or re.fullmatch(r"rmo?", lowered)
    )


def _clean_item_label(label: str) -> str:
    label = re.sub(r"^(?:[*>+\-•]\s*)+", "", label).strip()
    label = re.sub(r"\b[RAM]{0,2}$", "", label, flags=re.IGNORECASE).strip()
    label = re.sub(r"\s+(?:x\s*)?\d{1,3}\)?$", "", label, flags=re.IGNORECASE).strip()
    label = re.sub(r"\s+(?:x\s*)?\d{1,3}$", "", label, flags=re.IGNORECASE).strip()
    return re.sub(r"\s+", " ", label).strip(" .:-\t")


def _amount_from_money_match(match: re.Match) -> Decimal:
    groupdict = match.groupdict()
    if "amount" in groupdict and groupdict.get("amount"):
        return Decimal(groupdict["amount"].replace(",", ".")).quantize(CENT)
    if "digits" in groupdict and groupdict.get("digits"):
        digits = groupdict["digits"]
        return Decimal(f"{digits[:-2]}.{digits[-2:]}").quantize(CENT)
    return Decimal(f"{groupdict['whole']}.{groupdict['cents']}").quantize(CENT)


def _is_quantity_only_label(label: str) -> bool:
    return bool(re.fullmatch(r"(?:x\s*)?\d{1,3}", label.strip(), re.IGNORECASE))


def _looks_like_pending_item_label(line: str) -> bool:
    cleaned = _clean_item_label(line)
    lowered = cleaned.lower()
    if len(cleaned) < 3:
        return False
    if _contains_any(lowered, NOISE_WORDS + SERVICE_WORDS + TAX_WORDS + METADATA_WORDS):
        return False
    if _looks_like_address_or_code(cleaned):
        return False
    if MONEY_PATTERN.search(cleaned) or OCR_MONEY_PATTERN.search(cleaned) or COMPACT_RM_PATTERN.search(cleaned):
        return False
    return any(char.isalpha() for char in cleaned)


def _parse_inline_addon_line(line: str) -> tuple[str, Decimal] | None:
    match = re.search(r"(?P<label>[A-Za-z][A-Za-z\s*]+)\s*\+(?P<amount>\d{1,4}[.,]\d{2})", line)
    if not match:
        return None
    label = _clean_item_label(match.group("label"))
    if not label or _looks_like_metadata(label):
        return None
    return label, Decimal(match.group("amount").replace(",", ".")).quantize(CENT)


def _cleanup_restaurant_name(line: str) -> str:
    line = re.sub(r"^\W+", "", line)
    return re.sub(r"\s+", " ", line).strip(" .:-\t")


def _looks_like_address_or_code(value: str) -> bool:
    lowered = value.lower()
    return bool(
        re.search(r"\b(blvd|street|st\.?|jalan|jln|road|rd\.?|tower|level|lot|unit|floor|kuala|chicago|tel)\b", lowered)
        or re.search(r"\d{4,}", value)
        or re.search(r"[#:] ?\w*\d", value)
    )


def _clean_person(person: str) -> str:
    return re.sub(r"\s+", " ", person).strip()


def _assignment_clauses(note: str) -> list[str]:
    clauses = re.split(r"[;\n.]+", note.lower())
    return [clause.strip() for clause in clauses if clause.strip()]


def _shared_phrase_found(clause: str) -> bool:
    return any(word in clause for word in ("everyone", "everybody", "all shared", "shared by all"))


def _split_amount(amount: Decimal, count: int) -> list[Decimal]:
    base = (amount / count).quantize(CENT, rounding=ROUND_HALF_UP)
    parts = [base for _ in range(count)]
    drift = amount - sum(parts, Decimal("0"))
    index = 0
    while drift != 0:
        step = CENT if drift > 0 else -CENT
        parts[index] += step
        drift -= step
        index = (index + 1) % count
    return parts


def _normalize_item_portions(
    assignment: list[str] | dict[str, Any],
    item_totals: dict[str, Decimal],
) -> dict[str, Decimal]:
    if isinstance(assignment, dict):
        portions = {}
        for person, portion in assignment.items():
            if person not in item_totals:
                continue
            portion_value = Decimal(str(portion))
            if portion_value > 0:
                portions[person] = portion_value
        return portions

    return {person: Decimal("1") for person in assignment if person in item_totals}


def _split_by_portions(amount: Decimal, portions: dict[str, Decimal]) -> dict[str, Decimal]:
    total_portions = sum(portions.values(), Decimal("0"))
    if total_portions == 0:
        return {}

    raw_parts = {person: amount * portion / total_portions for person, portion in portions.items()}
    rounded = {person: value.quantize(CENT, rounding=ROUND_HALF_UP) for person, value in raw_parts.items()}
    drift = amount - sum(rounded.values(), Decimal("0"))
    people_by_portion = sorted(portions, key=portions.get, reverse=True)
    index = 0
    while drift != 0 and people_by_portion:
        step = CENT if drift > 0 else -CENT
        rounded[people_by_portion[index]] += step
        drift -= step
        index = (index + 1) % len(people_by_portion)
    return rounded


def _split_proportionally(
    charge: Decimal,
    item_totals: dict[str, Decimal],
    subtotal: Decimal,
) -> dict[str, Decimal]:
    if charge == 0:
        return {person: Decimal("0.00") for person in item_totals}
    if subtotal == 0:
        return dict(zip(item_totals, _split_amount(charge, len(item_totals))))

    raw_parts = {person: charge * item_total / subtotal for person, item_total in item_totals.items()}
    rounded = {person: value.quantize(CENT, rounding=ROUND_HALF_UP) for person, value in raw_parts.items()}
    drift = charge - sum(rounded.values(), Decimal("0"))
    people_by_share = sorted(item_totals, key=item_totals.get, reverse=True)
    index = 0
    while drift != 0 and people_by_share:
        step = CENT if drift > 0 else -CENT
        rounded[people_by_share[index]] += step
        drift -= step
        index = (index + 1) % len(people_by_share)
    return rounded


def _recommendations(bill: dict[str, Any], assignments: dict[str, list[str]]) -> list[str]:
    notes = []
    notes.extend(bill.get("validation", {}).get("warnings", []))
    unassigned = [item["name"] for item in bill["items"] if not assignments.get(item["id"])]
    if unassigned:
        notes.append(f"Check unassigned items: {', '.join(unassigned)}")
    if Decimal(str(bill["service_charge"])) == 0:
        notes.append("No service charge was detected.")
    if Decimal(str(bill["tax"])) == 0:
        notes.append("No tax was detected.")
    return notes


def _user_id(context: Any | None) -> str:
    return getattr(context, "user_id", "demo_user")
