"""Agent-style orchestration for restaurant bill splitting."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.tools import (
    assign_items_from_note,
    calculate_bill_split,
    parse_bill_text,
    remember_split_preferences,
)


@dataclass
class MockToolContext:
    user_id: str = "demo_user"
    session_id: str = field(default_factory=lambda: f"session_{uuid4().hex[:8]}")


class ToolAgent:
    """Tiny local agent wrapper around one responsibility."""

    def __init__(self, name: str, description: str, tool):
        self.name = name
        self.description = description
        self.tool = tool

    def run(self, *args, **kwargs):
        return self.tool(*args, **kwargs)


class BillSplitAgentSystem:
    """Sequential bill splitting agent with parser, assignment, and calculator tools."""

    def __init__(self):
        self.bill_parser = ToolAgent(
            name="BillParser",
            description="Extracts restaurant, items, service charge, and tax from bill text.",
            tool=parse_bill_text,
        )
        self.preference_agent = ToolAgent(
            name="PreferenceMemory",
            description="Stores recent diners for the current user/session.",
            tool=remember_split_preferences,
        )
        self.assignment_agent = ToolAgent(
            name="ItemAssignmentAgent",
            description="Maps items to diners from a natural-language sharing note.",
            tool=assign_items_from_note,
        )
        self.calculator_agent = ToolAgent(
            name="SplitCalculator",
            description="Calculates item shares plus proportional service and tax.",
            tool=calculate_bill_split,
        )

    def run(
        self,
        bill_text: str,
        people: list[str],
        assignment_note: str = "",
        context: MockToolContext | None = None,
    ) -> dict[str, Any]:
        context = context or MockToolContext()
        bill = self.bill_parser.run(bill_text, context)
        self.preference_agent.run(people, context)
        assignments = self.assignment_agent.run(bill, people, assignment_note, context)
        return self.calculator_agent.run(bill, people, assignments, context)

    def run_with_assignments(
        self,
        bill_text: str,
        people: list[str],
        assignments: dict[str, list[str]],
        context: MockToolContext | None = None,
    ) -> dict[str, Any]:
        context = context or MockToolContext()
        bill = self.bill_parser.run(bill_text, context)
        self.preference_agent.run(people, context)
        return self.calculator_agent.run(bill, people, assignments, context)


AGENT_SYSTEM = BillSplitAgentSystem()


def get_agent_system() -> BillSplitAgentSystem:
    return AGENT_SYSTEM
