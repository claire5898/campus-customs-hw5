"""Exercise every MCP tool against a disposable copy of the HW5 database."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


HW5 = Path(__file__).resolve().parents[1]
SERVER = Path(__file__).with_name("server.py")
SOURCE_DB = HW5 / "data" / "campus_customs_new.db"

EXPECTED_TOOLS = {
    "get_shop_date",
    "check_order_stock",
    "check_rent_due",
    "evaluate_bulk_discount",
    "list_open_tickets",
    "get_ticket",
    "get_inventory",
    "get_pricing",
    "get_vendor",
    "list_vendors",
    "check_vendor_shipping_eligibility",
    "get_invoice",
    "list_unpaid_invoices",
    "get_lease",
    "get_cash_accounts",
    "update_ticket_status",
    "record_approved_invoice_payment",
    "record_approved_purchase",
}


def _payload(result: object) -> str:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return str(structured)
    return "\n".join(block.text for block in result.content if hasattr(block, "text"))


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="campus-customs-mcp-") as temp_dir:
        test_db = Path(temp_dir) / "campus_customs_test.db"
        shutil.copy2(SOURCE_DB, test_db)
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
            env={**os.environ, "CAMPUS_CUSTOMS_DB": str(test_db)},
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                available = {tool.name for tool in listed.tools}
                missing = EXPECTED_TOOLS - available
                assert not missing, f"MCP tools missing: {sorted(missing)}"
                assert available == EXPECTED_TOOLS, f"Unexpected MCP tools: {sorted(available - EXPECTED_TOOLS)}"

                calls = [
                    ("get_shop_date", {}),
                    ("check_order_stock", {"ticket_id": 101}),
                    ("check_rent_due", {"ticket_id": 102}),
                    ("evaluate_bulk_discount", {"ticket_id": 103}),
                    ("list_open_tickets", {}),
                    ("get_ticket", {"ticket_id": 101}),
                    ("get_inventory", {"sku": "CC-TEE-WHITE", "size": "S"}),
                    ("get_pricing", {"sku": "CC-HOOD-NAVY"}),
                    ("get_vendor", {"vendor_id": 1}),
                    ("list_vendors", {}),
                    ("check_vendor_shipping_eligibility", {"vendor_id": 1}),
                    ("get_invoice", {"invoice_id": 501}),
                    ("list_unpaid_invoices", {}),
                    ("get_lease", {"lease_id": 1}),
                    ("get_cash_accounts", {}),
                    ("update_ticket_status", {"ticket_id": 101, "status": "in_progress"}),
                ]

                for name, arguments in calls:
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, f"{name} failed: {_payload(result)}"
                    print(f"PASS {name}")

                # Verify the insufficient-cash refusal and successful payment update
                # without changing the user's working database.
                with sqlite3.connect(test_db) as connection:
                    connection.execute("UPDATE cash_accounts SET balance = 1 WHERE name = 'checking'")
                refused = await session.call_tool(
                    "record_approved_invoice_payment",
                    {"invoice_id": 501, "account": "checking", "approved_by": "Test approver"},
                )
                assert not refused.isError and "Insufficient cash" in _payload(refused), _payload(refused)
                print("PASS record_approved_invoice_payment (insufficient cash refused)")

                with sqlite3.connect(test_db) as connection:
                    connection.execute("UPDATE cash_accounts SET balance = 3400 WHERE name = 'checking'")
                paid = await session.call_tool(
                    "record_approved_invoice_payment",
                    {"invoice_id": 501, "account": "checking", "approved_by": "Test approver"},
                )
                assert not paid.isError and "paid" in _payload(paid), _payload(paid)
                print("PASS record_approved_invoice_payment (approved payment recorded)")

                with sqlite3.connect(test_db) as connection:
                    connection.execute("UPDATE cash_accounts SET balance = 1 WHERE name = 'checking'")
                refused_purchase = await session.call_tool(
                    "record_approved_purchase",
                    {"amount": 2, "account": "checking", "approved_by": "Test approver"},
                )
                assert "Insufficient cash" in _payload(refused_purchase), _payload(refused_purchase)
                print("PASS record_approved_purchase (insufficient cash refused)")

                with sqlite3.connect(test_db) as connection:
                    connection.execute("UPDATE cash_accounts SET balance = 3400 WHERE name = 'checking'")
                purchase = await session.call_tool(
                    "record_approved_purchase",
                    {"amount": 100, "account": "checking", "approved_by": "Test approver"},
                )
                assert not purchase.isError and "vendor_order_placed" in _payload(purchase), _payload(purchase)
                assert "'remaining_balance': 3300.0" in _payload(purchase), _payload(purchase)
                print("PASS record_approved_purchase (cash outflow recorded; no vendor order placed)")


if __name__ == "__main__":
    asyncio.run(main())
