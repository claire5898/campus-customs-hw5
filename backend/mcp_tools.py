"""Read-only MCP adapters and the shared FastMCP session lifecycle."""

from __future__ import annotations

import os
import sys
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic_ai import RunContext

from .models import TeamRuntime


BACKEND_DIR = Path(__file__).resolve().parent
HW5_DIR = BACKEND_DIR.parent
MCP_SERVER = HW5_DIR / "mcp_server" / "server.py"
WORKING_DATABASE = HW5_DIR / "data" / "campus_customs_new.db"


def mcp_result_to_value(result: Any) -> Any:
    """Normalize an MCP structured result or JSON text into Python values."""
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    content = getattr(result, "content", [])
    texts = [item.text for item in content if getattr(item, "text", None)]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]
    return texts


async def _call(ctx: RunContext[TeamRuntime], tool_name: str, **arguments: Any) -> Any:
    runtime = ctx.deps
    common = {
        "agent": runtime.active_agents[-1] if runtime.active_agents else "Unknown",
        "agent_chain": list(runtime.active_agents),
        "tool_name": tool_name,
        "tool_input": arguments,
    }
    runtime.audit.append("mcp_tool_started", **common)
    try:
        result = await runtime.mcp.call_tool(tool_name, arguments)
        output = mcp_result_to_value(result)
        if getattr(result, "isError", False):
            runtime.audit.append("mcp_tool_failed", **common, tool_output=output)
            raise RuntimeError(f"MCP tool {tool_name} returned an error: {output}")
        runtime.audit.append("mcp_tool_completed", **common, tool_output=output)
        return output
    except Exception as error:
        if not isinstance(error, RuntimeError) or "returned an error" not in str(error):
            runtime.audit.append(
                "mcp_tool_failed", **common,
                error_type=type(error).__name__, error=str(error),
            )
        raise


async def get_shop_date(ctx: RunContext[TeamRuntime]) -> Any:
    """Read the shop business date from desk.date_today."""
    return await _call(ctx, "get_shop_date")


async def list_open_tickets(ctx: RunContext[TeamRuntime]) -> Any:
    """Read open tickets with their linked due-date facts."""
    return await _call(ctx, "list_open_tickets")


async def get_ticket(ctx: RunContext[TeamRuntime], ticket_id: int) -> Any:
    """Read one ticket and linked invoice or lease details."""
    return await _call(ctx, "get_ticket", ticket_id=ticket_id)


async def check_order_stock(ctx: RunContext[TeamRuntime], ticket_id: int) -> Any:
    """Check the exact requested item, size, quantity, and stock."""
    return await _call(ctx, "check_order_stock", ticket_id=ticket_id)


async def check_rent_due(ctx: RunContext[TeamRuntime], ticket_id: int) -> Any:
    """Compare rent ticket due date with the shop business date."""
    return await _call(ctx, "check_rent_due", ticket_id=ticket_id)


async def evaluate_bulk_discount(ctx: RunContext[TeamRuntime], ticket_id: int) -> Any:
    """Read stock and recorded price/margin facts for a price-override ticket."""
    return await _call(ctx, "evaluate_bulk_discount", ticket_id=ticket_id)


async def get_inventory(
    ctx: RunContext[TeamRuntime], sku: str, size: str | None = None
) -> Any:
    """Read inventory for a SKU and optional size."""
    return await _call(ctx, "get_inventory", sku=sku, size=size)


async def get_pricing(ctx: RunContext[TeamRuntime], sku: str) -> Any:
    """Read the recorded unit cost and list price for a SKU."""
    return await _call(ctx, "get_pricing", sku=sku)


async def get_vendor(ctx: RunContext[TeamRuntime], vendor_id: int) -> Any:
    """Read vendor specialty, lead time, and unpaid invoice count."""
    return await _call(ctx, "get_vendor", vendor_id=vendor_id)


async def list_vendors(ctx: RunContext[TeamRuntime]) -> Any:
    """List vendors and their database-backed lead-time and shipping facts."""
    return await _call(ctx, "list_vendors")


async def check_vendor_shipping_eligibility(
    ctx: RunContext[TeamRuntime], vendor_id: int
) -> Any:
    """Check whether an unpaid invoice blocks a vendor shipment."""
    return await _call(ctx, "check_vendor_shipping_eligibility", vendor_id=vendor_id)


async def get_invoice(ctx: RunContext[TeamRuntime], invoice_id: int) -> Any:
    """Read invoice and linked vendor details."""
    return await _call(ctx, "get_invoice", invoice_id=invoice_id)


async def list_unpaid_invoices(ctx: RunContext[TeamRuntime]) -> Any:
    """List unpaid invoices and determine overdue state using the shop date."""
    return await _call(ctx, "list_unpaid_invoices")


async def get_cash_accounts(ctx: RunContext[TeamRuntime]) -> Any:
    """Read current cash balances by account."""
    return await _call(ctx, "get_cash_accounts")


async def get_lease(ctx: RunContext[TeamRuntime], lease_id: int) -> Any:
    """Read lease, rent amount, and due-date details."""
    return await _call(ctx, "get_lease", lease_id=lease_id)


MCP_READ_FUNCTIONS = {
    "get_shop_date": get_shop_date,
    "list_open_tickets": list_open_tickets,
    "get_ticket": get_ticket,
    "check_order_stock": check_order_stock,
    "check_rent_due": check_rent_due,
    "evaluate_bulk_discount": evaluate_bulk_discount,
    "get_inventory": get_inventory,
    "get_pricing": get_pricing,
    "get_vendor": get_vendor,
    "list_vendors": list_vendors,
    "check_vendor_shipping_eligibility": check_vendor_shipping_eligibility,
    "get_invoice": get_invoice,
    "list_unpaid_invoices": list_unpaid_invoices,
    "get_cash_accounts": get_cash_accounts,
    "get_lease": get_lease,
}


@asynccontextmanager
async def open_mcp_session() -> AsyncIterator[ClientSession]:
    """Launch the FastMCP server against the mutable working-copy database."""
    if not MCP_SERVER.is_file():
        raise FileNotFoundError(f"MCP server not found: {MCP_SERVER}")
    if not WORKING_DATABASE.is_file():
        raise FileNotFoundError(f"Working database not found: {WORKING_DATABASE}")
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],
        env={**os.environ, "CAMPUS_CUSTOMS_DB": str(WORKING_DATABASE)},
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session
