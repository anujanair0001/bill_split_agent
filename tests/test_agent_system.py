from decimal import Decimal

from src.agents import get_agent_system


SAMPLE_BILL = """Noodle House
Pasta 18.00
Burger 22.00
Fries 12.00
Service Charge 5.20
SST 3.12
Total 60.32
"""


def test_agent_system_runs_end_to_end():
    plan = get_agent_system().run(
        bill_text=SAMPLE_BILL,
        people=["Alice", "Bob"],
        assignment_note="Alice had pasta; Bob had burger; everyone shared fries",
    )

    assert plan["restaurant_name"] == "Noodle House"
    assert len(plan["splits"]) == 2
    assert sum((split["total"] for split in plan["splits"]), Decimal("0")) == plan["detected_total"]
