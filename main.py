"""Interactive CLI entry point for BillSplit Agent."""

import argparse

from src.tools import (
    OcrError,
    calculate_bill_split,
    extract_receipt_text,
    parse_bill_text,
    remember_split_preferences,
)
from src.agents import MockToolContext, get_agent_system
from src.utils import format_split_summary, get_memory_stats


DEMO_BILL = """Noodle House
Pasta 18.00
Burger 22.00
Fries 12.00
Service Charge 5.20
SST 3.12
Total 60.32
"""


def run_demo(
    bill_text: str = DEMO_BILL,
    people: list[str] | None = None,
    assignment_note: str = "Alice had pasta; Bob had burger; everyone shared fries",
) -> dict:
    people = people or ["Alice", "Bob"]
    context = MockToolContext()
    agent_system = get_agent_system()
    plan = agent_system.run(bill_text=bill_text, people=people, assignment_note=assignment_note, context=context)
    print(format_split_summary(plan))
    print(f"Memory: {get_memory_stats()['total_keys']} keys")
    return plan


def run_interactive(bill_text: str | None = None) -> dict:
    context = MockToolContext()
    bill_text = bill_text or _read_receipt_text()
    bill = parse_bill_text(bill_text, context)

    print()
    print(f"Restaurant: {bill['restaurant_name'] or 'Unknown'}")
    print("Detected items:")
    for index, item in enumerate(bill["items"], 1):
        print(f"  {index}. {item['name']} - {item['price']:.2f}")
    print(f"Service charge: {bill['service_charge']:.2f}")
    print(f"Tax: {bill['tax']:.2f}")
    print(f"Detected total: {bill['detected_total']:.2f}")

    people = _ask_people()
    remember_split_preferences(people, context)
    assignments = _ask_item_assignments(bill, people)
    plan = calculate_bill_split(bill, people, assignments, context)

    print()
    print(format_split_summary(plan))
    print(f"Memory: {get_memory_stats()['total_keys']} keys")
    return plan


def _read_receipt_text() -> str:
    print("Paste the receipt text below. Type END on its own line when finished.")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)

    text = "\n".join(lines).strip()
    if not text:
        raise ValueError("Receipt text is required.")
    return text


def _ask_people() -> list[str]:
    while True:
        raw = input("\nWho ate? Enter names separated by commas: ").strip()
        people = [name.strip() for name in raw.split(",") if name.strip()]
        if people:
            return people
        print("Please enter at least one name.")


def _ask_item_assignments(bill: dict, people: list[str]) -> dict[str, list[str]]:
    assignments = {}
    print()
    print("For each item, enter who ate it.")
    print("Use names, numbers, comma-separated values, or 'all'.")
    for index, person in enumerate(people, 1):
        print(f"  {index} = {person}")

    for item in bill["items"]:
        while True:
            answer = input(f"{item['name']} ({item['price']:.2f}): ").strip()
            eaters = _parse_eaters(answer, people)
            if eaters:
                assignments[item["id"]] = eaters
                break
            print("Please enter at least one valid person, number, or 'all'.")

    return assignments


def _parse_eaters(answer: str, people: list[str]) -> list[str]:
    if answer.lower() in {"all", "everyone", "everybody"}:
        return people[:]

    selected = []
    tokens = [token.strip() for token in answer.replace("&", ",").split(",") if token.strip()]
    people_by_lower = {person.lower(): person for person in people}

    for token in tokens:
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(people):
                selected.append(people[index])
            continue

        person = people_by_lower.get(token.lower())
        if person:
            selected.append(person)

    return list(dict.fromkeys(selected))


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a restaurant bill with a local agent workflow.")
    parser.add_argument("--bill-file", help="Path to a text file containing receipt text.")
    parser.add_argument("--image-file", help="Path to a receipt image or PDF to read with OCR.")
    parser.add_argument("--demo", action="store_true", help="Run the built-in demo bill.")
    parser.add_argument("--people", help="Comma-separated diner names for demo/note mode.")
    parser.add_argument(
        "--assignments",
        help="Natural-language item assignment note for non-interactive mode.",
    )
    args = parser.parse_args()

    bill_text = None
    if args.image_file:
        try:
            bill_text = extract_receipt_text(args.image_file)
            print("OCR completed. Please review the detected items below.")
        except OcrError as error:
            print(f"OCR error: {error}")
            print()
            bill_text = _read_receipt_text()

    if args.bill_file:
        with open(args.bill_file, encoding="utf-8") as handle:
            bill_text = handle.read()

    if args.demo:
        people = _people_from_arg(args.people) or ["Alice", "Bob"]
        assignment_note = args.assignments or "Alice had pasta; Bob had burger; everyone shared fries"
        run_demo(bill_text=bill_text or DEMO_BILL, people=people, assignment_note=assignment_note)
        return

    if args.people and args.assignments:
        people = _people_from_arg(args.people)
        get_agent_system()
        run_demo(bill_text=bill_text or _read_receipt_text(), people=people, assignment_note=args.assignments)
        return

    run_interactive(bill_text=bill_text)


def _people_from_arg(value: str | None) -> list[str]:
    if not value:
        return []
    return [person.strip() for person in value.split(",") if person.strip()]


if __name__ == "__main__":
    main()
