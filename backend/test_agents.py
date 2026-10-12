"""Offline and read-only checks for the Campus Customs PydanticAI team."""

from __future__ import annotations

import unittest
from datetime import date
import json
from tempfile import TemporaryDirectory
from pathlib import Path

from pydantic_ai.models.test import TestModel

from backend.agent_factory import READ_TOOLS, PROMPT_DIR, prompt_for
from backend.audit import AuditTrail
from backend.config import MODEL_NAME
from backend.mcp_tools import mcp_result_to_value, open_mcp_session
from backend.team import AGENT_NAMES, build_agent_team
from backend.team import (
    MAX_DELEGATION_DEPTH,
    MAX_MODEL_REQUESTS,
    MAX_TOOL_CALLS,
    MAX_TOTAL_TOKENS,
)


class AgentTeamTests(unittest.TestCase):
    def test_audit_trail_appends_and_preserves_prior_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            audit_path = Path(temp_dir) / "audit_trail.json"
            AuditTrail(audit_path, run_id="first-run").append(
                "agent_started", agent="Boss", task="Review ticket 101"
            )
            AuditTrail(audit_path, run_id="second-run").append(
                "agent_completed", agent="Inventory", report={"summary": "Checked stock"}
            )

            events = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(len(events), 2)
            self.assertEqual([event["sequence"] for event in events], [1, 2])
            self.assertEqual(
                [event["run_id"] for event in events], ["first-run", "second-run"]
            )
            self.assertEqual(events[0]["task"], "Review ticket 101")
            self.assertEqual(events[1]["report"]["summary"], "Checked stock")

    def test_audit_trail_preserves_unicode_when_appending(self) -> None:
        with TemporaryDirectory() as temp_dir:
            audit_path = Path(temp_dir) / "audit_trail.json"
            AuditTrail(audit_path, run_id="first-run").append(
                "agent_completed", summary="We’re checking the customer’s order."
            )
            AuditTrail(audit_path, run_id="second-run").append(
                "run_completed", summary="Verified — no payment was made."
            )

            events = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual([event["sequence"] for event in events], [1, 2])
            self.assertEqual(events[0]["summary"], "We’re checking the customer’s order.")
            self.assertEqual(events[1]["summary"], "Verified — no payment was made.")

    def test_all_roles_have_scoped_tools_and_peer_delegation(self) -> None:
        team = build_agent_team(TestModel())
        self.assertEqual(set(team), set(AGENT_NAMES))

        for name, agent in team.items():
            available = {tool.name for tool in agent._function_toolset.tools.values()}
            self.assertTrue((PROMPT_DIR / f"{name.lower().replace(' ', '_')}.md").is_file())
            self.assertIn(name, prompt_for(name))
            self.assertTrue(set(READ_TOOLS[name]).issubset(available))
            self.assertNotIn("record_approved_invoice_payment", available)
            self.assertNotIn("update_ticket_status", available)
            self.assertNotIn("send_email", available)
            for peer in AGENT_NAMES:
                if peer != name:
                    self.assertIn(
                        f"delegate_to_{peer.lower().replace(' ', '_')}", available
                    )
                else:
                    self.assertNotIn(
                        f"delegate_to_{peer.lower().replace(' ', '_')}", available
                    )

    def test_prompts_cover_role_boundaries_and_shop_rules(self) -> None:
        prompts = {role: prompt_for(role).lower() for role in AGENT_NAMES}
        shared_rules = (
            "desk.date_today",
            "vendors.lead_days",
            "open unpaid invoice",
            "human approval",
            "never",
        )
        for prompt in prompts.values():
            for rule in shared_rules:
                self.assertIn(rule, prompt)
        self.assertIn("do not invent vendors", prompts["Inventory"])
        self.assertIn("recommend payments only for human approval", prompts["Accounting"])
        self.assertIn("do not send them", prompts["Customer Service"])
        self.assertIn("computer's current date", prompts["Facilities"])
        self.assertIn("never mark a ticket resolved", prompts["Boss"])
        self.assertIn("get_pricing", READ_TOOLS["Accounting"])

    def test_default_model_and_run_guards(self) -> None:
        team = build_agent_team()
        self.assertEqual(MODEL_NAME, "gpt-6-luna")
        self.assertEqual(
            {agent.model.model_name for agent in team.values()},
            {"gpt-6-luna"},
        )
        self.assertEqual(MAX_DELEGATION_DEPTH, 6)
        self.assertGreater(MAX_MODEL_REQUESTS, 0)
        self.assertGreater(MAX_TOOL_CALLS, 0)
        self.assertEqual(MAX_TOTAL_TOKENS, 50_000)


class ReadOnlyMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ticket_tools_return_working_database_values(self) -> None:
        expected = {
            "check_order_stock": {
                "ticket_id": 101,
                "ticket_status": "open",
                "sku": "CC-TEE-WHITE",
                "size": "S",
                "requested_qty": 1,
                "available_qty": 0,
                "can_fulfill": False,
                "stock_shortfall": 1,
                "inventory_item": {
                    "sku": "CC-TEE-WHITE",
                    "name": "Classic Bulldog Tee",
                    "size": "S",
                    "qty": 0,
                    "location": "Aisle B",
                },
            },
            "check_rent_due": {
                "ticket_id": 102,
                "ticket_status": "open",
                "lease_id": 1,
                "space_name": "Chapel Street shop",
                "landlord": "Elm City Properties",
                "monthly_rent": 2400.0,
                "next_due": "2026-09-02",
                "shop_date": "2026-08-31",
                "days_until_due": 2,
                "due_state": "upcoming",
            },
            "evaluate_bulk_discount": {
                "ticket_id": 103,
                "ticket_status": "open",
                "sku": "CC-HOOD-NAVY",
                "size": "M",
                "requested_qty": 20,
                "available_qty": 8,
                "stock_shortfall": 12,
                "unit_cost_from_pricing": 22.0,
                "list_price_from_pricing": 58.0,
                "unit_margin_at_list_price": 36.0,
                "list_price_total": 1160.0,
                "cost_total": 440.0,
                "gross_margin_total_at_list_price": 720.0,
                "discount_policy": "No discount rule is stored in the database; no discount is recommended or approved by this tool.",
            },
        }
        arguments = {
            "check_order_stock": {"ticket_id": 101},
            "check_rent_due": {"ticket_id": 102},
            "evaluate_bulk_discount": {"ticket_id": 103},
        }

        async with open_mcp_session() as session:
            for tool_name, expected_output in expected.items():
                result = await session.call_tool(tool_name, arguments[tool_name])
                actual_output = mcp_result_to_value(result)
                # Ticket status is intentionally mutable; verify it without
                # coupling these database-backed checks to a particular run state.
                self.assertIn(actual_output.pop("ticket_status"), {"open", "resolved"})
                expected_output.pop("ticket_status")
                self.assertEqual(actual_output, expected_output)

    async def test_vendor_and_unpaid_invoice_tools_use_database_facts(self) -> None:
        async with open_mcp_session() as session:
            vendor_result = await session.call_tool("list_vendors", {})
            invoice_result = await session.call_tool("list_unpaid_invoices", {})
        vendors = mcp_result_to_value(vendor_result)
        invoices = mcp_result_to_value(invoice_result)
        if isinstance(vendors, dict) and "result" in vendors:
            vendors = vendors["result"]
        if isinstance(invoices, dict) and "result" in invoices:
            invoices = invoices["result"]

        self.assertTrue(vendors)
        for vendor in vendors:
            self.assertIn("id", vendor)
            self.assertIn("specialty", vendor)
            self.assertIn("lead_days", vendor)
            self.assertIn("unpaid_invoice_count", vendor)
            self.assertEqual(
                vendor["eligible_to_ship"], vendor["unpaid_invoice_count"] == 0
            )
        for invoice in invoices:
            self.assertEqual(invoice["shop_date"], "2026-08-31")
            expected_overdue = date.fromisoformat(invoice["due_date"]) < date.fromisoformat(
                invoice["shop_date"]
            )
            self.assertEqual(invoice["overdue"], expected_overdue)
            self.assertNotIn(invoice["status"].lower(), {"paid", "closed"})


if __name__ == "__main__":
    unittest.main()
