from decimal import Decimal

from src.tools import assign_items_from_note, calculate_bill_split, parse_bill_text


def test_parse_bill_text_detects_items_and_charges():
    bill = parse_bill_text(
        """Noodle House
        Pasta 18.00
        Burger 22.00
        Service Charge 4.00
        SST 2.00
        Total 46.00
        """
    )

    assert bill["restaurant_name"] == "Noodle House"
    assert [item["name"] for item in bill["items"]] == ["Pasta", "Burger"]
    assert bill["service_charge"] == Decimal("6.00")
    assert bill["tax"] == Decimal("0.00")
    assert bill["detected_total"] == Decimal("46.00")


def test_agent_tools_assign_and_split_shared_items():
    bill = parse_bill_text(
        """Noodle House
        Pasta 18.00
        Burger 22.00
        Fries 12.00
        Service Charge 5.20
        SST 3.12
        Total 60.32
        """
    )
    people = ["Alice", "Bob"]
    assignments = assign_items_from_note(
        bill,
        people,
        "Alice had pasta; Bob had burger; everyone shared fries",
    )

    plan = calculate_bill_split(bill, people, assignments)

    totals = {split["person"]: split["total"] for split in plan["splits"]}
    assert totals["Alice"] == Decimal("27.84")
    assert totals["Bob"] == Decimal("32.48")
    assert sum(totals.values(), Decimal("0")) == bill["detected_total"]


def test_weighted_item_portions_split_by_count():
    bill = parse_bill_text(
        """Noodle House
        Dumplings 40.00
        Service Charge 0.00
        SST 0.00
        Total 40.00
        """
    )
    people = ["Alice", "Bob"]
    item_id = bill["items"][0]["id"]

    plan = calculate_bill_split(bill, people, {item_id: {"Alice": 3, "Bob": 1}})

    totals = {split["person"]: split["total"] for split in plan["splits"]}
    assert totals["Alice"] == Decimal("30.00")
    assert totals["Bob"] == Decimal("10.00")


def test_noisy_ocr_receipt_skips_invoice_metadata():
    bill = parse_bill_text(
        """Invoice |
        Din by Din Tai F
        Lo14i7 & as70 na a
        241, Petron ia KLOC
        Si aS Twin Tower, S008 WB
        Tel +603 21810323
        lub Sdn Bhd 200701007248 (765249.
        ST ID: W10-1808-310z0686
        set Table61-] ES Sa
        yy INVOice:202505 12097 Customers:9
        Time:2026/05/13 14.42
        Counter52 Staff:602201
        Crispy Mush WT*6 1 RM17.45
        Chic S*PeanutNDL 1 RM24.53
        Chic*Scal! NDL 1 RM24.53
        *PNut MushWT NDL 1 RM26.41
        Shic Chop FR *S 1 RM31.60
        joc XLB *10 a _ RM30.19
        SUBTOTAL: RM303.27
        TAX: RM18.20
        Grand Total
        RM321.45
        DuitNow
        Thank you and Please come again
        """
    )

    item_names = [item["name"] for item in bill["items"]]
    assert bill["restaurant_name"] == "Din by Din Tai F"
    assert "Counter52 Staff:602201" not in item_names
    assert "yy INVOice:202505 12097 Customers:9" not in item_names
    assert item_names[:3] == ["Crispy Mush WT*6", "Chic S*PeanutNDL", "Chic*Scal! NDL"]
    assert bill["service_charge"] == Decimal("18.20")
    assert bill["tax"] == Decimal("0.00")
    assert bill["receipt_subtotal"] == Decimal("303.27")
    assert bill["receipt_total"] == Decimal("321.45")
