"""HTTP-level checks for the FastAPI dashboard routes; no live model calls."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import main
from backend.models import AgentReport


class DashboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(main.app)

    def test_read_routes_return_ticket_status_cash_and_recent_events(self) -> None:
        tickets = self.client.get("/api/tickets")
        self.assertEqual(tickets.status_code, 200)
        ticket_rows = tickets.json()
        self.assertEqual([row["ticket_id"] for row in ticket_rows], [101, 102, 103])
        self.assertTrue(all("status" in row for row in ticket_rows))

        checking = self.client.get("/api/cash/checking")
        self.assertEqual(checking.status_code, 200)
        self.assertEqual(checking.json()["name"], "checking")
        self.assertIn("balance", checking.json())

        events = self.client.get("/api/events?limit=10")
        self.assertEqual(events.status_code, 200)
        self.assertLessEqual(events.json()["count"], 10)

    def test_ticket_run_is_scoped_to_requested_ticket(self) -> None:
        async def fake_mcp_call(tool_name: str, arguments: dict | None = None):
            return {"id": 101, "status": "open", "type": "customer_order"}

        report = AgentReport(agent="Boss", summary="Ticket 101 reviewed")
        with (
            patch.object(main, "_mcp_call", new=AsyncMock(side_effect=fake_mcp_call)),
            patch.object(main, "run_boss", new=AsyncMock(return_value=report)) as run_mock,
        ):
            response = self.client.post("/api/tickets/101/run")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ticket_id"], 101)
        self.assertEqual(response.json()["report"]["summary"], "Ticket 101 reviewed")
        task = run_mock.await_args.args[0]
        self.assertIn("ONLY open Campus Customs ticket 101", task)

    def test_ticket_resolution_requires_human_confirmation_and_uses_mcp(self) -> None:
        async def fake_mcp_call(tool_name: str, arguments: dict | None = None):
            if tool_name == "get_ticket":
                return {"id": 101, "status": "open"}
            return {"ticket_id": 101, "status": "resolved"}

        with patch.object(
            main, "_mcp_call", new=AsyncMock(side_effect=fake_mcp_call)
        ) as mcp_call, patch.object(main, "AuditTrail"):
            response = self.client.post(
                "/api/tickets/101/resolve",
                json={"resolved_by": "Claire", "confirmation": "RESOLVE TICKET"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "resolved")
        self.assertEqual(mcp_call.await_args_list[1].args[0], "update_ticket_status")

        rejected = self.client.post(
            "/api/tickets/101/resolve", json={"resolved_by": "Claire"}
        )
        self.assertEqual(rejected.status_code, 422)

    def test_writes_require_explicit_confirmation(self) -> None:
        payment = self.client.post(
            "/api/approvals/payment",
            json={"invoice_id": 501, "account": "checking", "approved_by": "Claire"},
        )
        self.assertEqual(payment.status_code, 422)

        reset = self.client.post("/api/database/reset", json={"confirmation": "yes"})
        self.assertEqual(reset.status_code, 422)


    def test_purchase_approval_records_outflow_through_mcp(self) -> None:
        with patch.object(
            main,
            "_mcp_call",
            new=AsyncMock(
                return_value={
                    "kind": "purchase",
                    "amount_paid": 125.0,
                    "remaining_balance": 3275.0,
                    "vendor_order_placed": False,
                }
            ),
        ) as mcp_call, patch.object(main, "AuditTrail"):
            response = self.client.post(
                "/api/approvals/purchase",
                json={
                    "amount": 125,
                    "account": "checking",
                    "approved_by": "Claire",
                    "confirmation": "APPROVE PURCHASE",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["remaining_balance"], 3275.0)
        self.assertFalse(response.json()["vendor_order_placed"])
        mcp_call.assert_awaited_once_with(
            "record_approved_purchase",
            {"amount": 125.0, "account": "checking", "approved_by": "Claire"},
        )

        rejected = self.client.post(
            "/api/approvals/purchase",
            json={"amount": 125, "account": "checking", "approved_by": "Claire"},
        )
        self.assertEqual(rejected.status_code, 422)

    def test_confirmed_reset_restores_working_copy_without_touching_original(self) -> None:
        with tempfile.TemporaryDirectory(prefix="campus-customs-reset-test-") as temp_dir:
            original = Path(temp_dir) / "original.db"
            working = Path(temp_dir) / "working.db"
            original.write_bytes(b"baseline database")
            working.write_bytes(b"changed working database")
            with (
                patch.object(main, "ORIGINAL_DATABASE", original),
                patch.object(main, "WORKING_DATABASE", working),
                patch.object(main, "AuditTrail"),
            ):
                response = self.client.post(
                    "/api/database/reset",
                    json={"confirmation": "RESET WORKING DATABASE"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(working.read_bytes(), b"baseline database")
            self.assertEqual(original.read_bytes(), b"baseline database")


if __name__ == "__main__":
    unittest.main()
