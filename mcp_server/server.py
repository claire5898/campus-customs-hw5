"""Campus Customs MCP tools backed by the HW5 working SQLite database."""

from __future__ import annotations

import sqlite3
import os
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Campus Customs Operations")
DATABASE = Path(
    os.environ.get(
        "CAMPUS_CUSTOMS_DB",
        str(Path(__file__).resolve().parents[1] / "data" / "campus_customs_new.db"),
    )
).expanduser().resolve()


def _connect() -> sqlite3.Connection:
    """Open the working copy only when a tool is called."""
    if not DATABASE.is_file():
        raise FileNotFoundError(f"Working database not found: {DATABASE}")
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _shop_date(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ValueError("The desk table does not contain a shop date")
    return str(row["date_today"])


@mcp.tool()
def get_shop_date() -> dict[str, str]:
    """Return the shop's configured business date from desk.date_today."""
    with _connect() as connection:
        return {"date_today": _shop_date(connection)}


@mcp.tool()
def check_order_stock(ticket_id: int) -> dict[str, Any]:
    """Check whether the exact quantity on a customer-order ticket is in stock."""
    with _connect() as connection:
        ticket = connection.execute(
            "SELECT id, type, sku, size, qty, status FROM tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        if ticket is None:
            return {"error": f"Ticket {ticket_id} was not found"}
        if ticket["type"] != "customer_order":
            return {"error": f"Ticket {ticket_id} is not a customer_order ticket"}
        if not ticket["sku"] or not ticket["size"] or ticket["qty"] is None:
            return {"error": f"Ticket {ticket_id} is missing SKU, size, or quantity"}

        stock = connection.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (ticket["sku"], ticket["size"]),
        ).fetchone()
        available = int(stock["qty"]) if stock else 0
        requested = int(ticket["qty"])
        return {
            "ticket_id": ticket_id,
            "ticket_status": ticket["status"],
            "sku": ticket["sku"],
            "size": ticket["size"],
            "requested_qty": requested,
            "available_qty": available,
            "can_fulfill": available >= requested,
            "stock_shortfall": max(requested - available, 0),
            "inventory_item": _dict(stock),
        }


@mcp.tool()
def check_rent_due(ticket_id: int) -> dict[str, Any]:
    """Compare a rent-notice ticket's lease due date with desk.date_today."""
    with _connect() as connection:
        row = connection.execute(
            """SELECT t.id AS ticket_id, t.type, t.status AS ticket_status,
                      t.lease_id, l.space_name, l.landlord, l.monthly_rent,
                      l.next_due, d.date_today
               FROM tickets AS t
               JOIN leases AS l ON l.id = t.lease_id
               CROSS JOIN desk AS d
               WHERE t.id = ?""",
            (ticket_id,),
        ).fetchone()
        if row is None:
            return {"error": f"Rent ticket {ticket_id} or its linked lease was not found"}
        if row["type"] != "rent_notice":
            return {"error": f"Ticket {ticket_id} is not a rent_notice ticket"}

        today = date.fromisoformat(str(row["date_today"]))
        due = date.fromisoformat(str(row["next_due"]))
        days_until_due = (due - today).days
        if days_until_due < 0:
            due_state = "overdue"
        elif days_until_due == 0:
            due_state = "due_today"
        else:
            due_state = "upcoming"
        return {
            "ticket_id": ticket_id,
            "ticket_status": row["ticket_status"],
            "lease_id": row["lease_id"],
            "space_name": row["space_name"],
            "landlord": row["landlord"],
            "monthly_rent": row["monthly_rent"],
            "next_due": row["next_due"],
            "shop_date": row["date_today"],
            "days_until_due": days_until_due,
            "due_state": due_state,
        }


@mcp.tool()
def evaluate_bulk_discount(ticket_id: int) -> dict[str, Any]:
    """Summarize recorded stock and list-price margin facts for a bulk-price ticket."""
    with _connect() as connection:
        ticket = connection.execute(
            "SELECT id, type, sku, size, qty, status FROM tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        if ticket is None:
            return {"error": f"Ticket {ticket_id} was not found"}
        if ticket["type"] != "price_override":
            return {"error": f"Ticket {ticket_id} is not a price_override ticket"}
        if not ticket["sku"] or not ticket["size"] or ticket["qty"] is None:
            return {"error": f"Ticket {ticket_id} is missing SKU, size, or quantity"}

        pricing = connection.execute(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?",
            (ticket["sku"],),
        ).fetchone()
        stock = connection.execute(
            "SELECT qty FROM inventory WHERE sku = ? AND size = ?",
            (ticket["sku"], ticket["size"]),
        ).fetchone()
        if pricing is None:
            return {"error": f"No pricing data found for SKU {ticket['sku']}"}

        requested = int(ticket["qty"])
        available = int(stock["qty"]) if stock else 0
        unit_cost = float(pricing["unit_cost"])
        list_price = float(pricing["list_price"])
        unit_margin = list_price - unit_cost
        list_total = list_price * requested
        cost_total = unit_cost * requested
        gross_margin_total = list_total - cost_total
        return {
            "ticket_id": ticket_id,
            "ticket_status": ticket["status"],
            "sku": ticket["sku"],
            "size": ticket["size"],
            "requested_qty": requested,
            "available_qty": available,
            "stock_shortfall": max(requested - available, 0),
            "unit_cost_from_pricing": unit_cost,
            "list_price_from_pricing": list_price,
            "unit_margin_at_list_price": round(unit_margin, 2),
            "list_price_total": round(list_total, 2),
            "cost_total": round(cost_total, 2),
            "gross_margin_total_at_list_price": round(gross_margin_total, 2),
            "discount_policy": "No discount rule is stored in the database; no discount is recommended or approved by this tool.",
        }


@mcp.tool()
def list_open_tickets() -> list[dict[str, Any]]:
    """List open tickets and flag linked invoices or rent dates overdue as of the shop date."""
    with _connect() as connection:
        today = _shop_date(connection)
        rows = connection.execute(
            """SELECT t.*, i.due_date AS invoice_due_date,
                      i.status AS invoice_status, i.amount AS invoice_amount,
                      l.next_due AS lease_next_due, l.monthly_rent
               FROM tickets AS t
               LEFT JOIN invoices AS i ON i.id = t.invoice_id
               LEFT JOIN leases AS l ON l.id = t.lease_id
               WHERE lower(t.status) = 'open'
               ORDER BY t.id"""
        ).fetchall()
        tickets: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            due_date = item.get("invoice_due_date") or item.get("lease_next_due")
            item["shop_date"] = today
            item["overdue"] = bool(due_date and str(due_date) < today)
            tickets.append(item)
        return tickets


@mcp.tool()
def get_ticket(ticket_id: int) -> dict[str, Any] | dict[str, str]:
    """Return a ticket with linked invoice or lease details, if present."""
    with _connect() as connection:
        row = connection.execute(
            """SELECT t.*, i.vendor_id, i.amount AS invoice_amount,
                      i.due_date AS invoice_due_date, i.status AS invoice_status,
                      l.landlord, l.space_name, l.monthly_rent, l.next_due AS lease_next_due
               FROM tickets AS t
               LEFT JOIN invoices AS i ON i.id = t.invoice_id
               LEFT JOIN leases AS l ON l.id = t.lease_id
               WHERE t.id = ?""",
            (ticket_id,),
        ).fetchone()
        return _dict(row) or {"error": f"Ticket {ticket_id} was not found"}


@mcp.tool()
def get_inventory(sku: str, size: str | None = None) -> list[dict[str, Any]]:
    """Look up stock by SKU and optionally size."""
    with _connect() as connection:
        if size:
            rows = connection.execute(
                "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
                (sku, size),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? ORDER BY size",
                (sku,),
            ).fetchall()
        return [dict(row) for row in rows]


@mcp.tool()
def get_pricing(sku: str) -> dict[str, Any] | dict[str, str]:
    """Return unit cost and list price for a SKU."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()
        return _dict(row) or {"error": f"No pricing found for SKU {sku}"}


@mcp.tool()
def get_vendor(vendor_id: int) -> dict[str, Any] | dict[str, str]:
    """Return vendor details, lead time, and unpaid invoice count."""
    with _connect() as connection:
        row = connection.execute(
            """SELECT v.id, v.name, v.specialty, v.lead_days,
                      COUNT(CASE WHEN lower(i.status) NOT IN ('paid', 'closed') THEN 1 END)
                          AS unpaid_invoice_count
               FROM vendors AS v
               LEFT JOIN invoices AS i ON i.vendor_id = v.id
               WHERE v.id = ?
               GROUP BY v.id""",
            (vendor_id,),
        ).fetchone()
        return _dict(row) or {"error": f"Vendor {vendor_id} was not found"}


@mcp.tool()
def list_vendors() -> list[dict[str, Any]]:
    """List recorded vendors, lead times, specialties, and shipment eligibility facts."""
    with _connect() as connection:
        rows = connection.execute(
            """SELECT v.id, v.name, v.specialty, v.lead_days,
                      COUNT(CASE WHEN lower(i.status) NOT IN ('paid', 'closed') THEN 1 END)
                          AS unpaid_invoice_count
               FROM vendors AS v
               LEFT JOIN invoices AS i ON i.vendor_id = v.id
               GROUP BY v.id
               ORDER BY v.id"""
        ).fetchall()
        vendors = []
        for row in rows:
            vendor = dict(row)
            vendor["eligible_to_ship"] = vendor["unpaid_invoice_count"] == 0
            vendors.append(vendor)
        return vendors


@mcp.tool()
def check_vendor_shipping_eligibility(vendor_id: int) -> dict[str, Any]:
    """Check whether a vendor can ship; any open unpaid invoice blocks shipment."""
    vendor = get_vendor(vendor_id)
    if "error" in vendor:
        return vendor
    eligible = vendor["unpaid_invoice_count"] == 0
    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor["name"],
        "lead_days": vendor["lead_days"],
        "eligible_to_ship": eligible,
        "reason": "No open unpaid invoices" if eligible else "Vendor has an unpaid invoice",
    }


@mcp.tool()
def get_invoice(invoice_id: int) -> dict[str, Any] | dict[str, str]:
    """Return an invoice and its vendor details."""
    with _connect() as connection:
        row = connection.execute(
            """SELECT i.*, v.name AS vendor_name, v.specialty, v.lead_days
               FROM invoices AS i JOIN vendors AS v ON v.id = i.vendor_id
               WHERE i.id = ?""",
            (invoice_id,),
        ).fetchone()
        return _dict(row) or {"error": f"Invoice {invoice_id} was not found"}


@mcp.tool()
def list_unpaid_invoices() -> list[dict[str, Any]]:
    """List unpaid invoices with vendor and overdue facts based on desk.date_today."""
    with _connect() as connection:
        today = date.fromisoformat(_shop_date(connection))
        rows = connection.execute(
            """SELECT i.id AS invoice_id, i.vendor_id, v.name AS vendor_name,
                      i.amount, i.due_date, i.status, i.description
               FROM invoices AS i
               JOIN vendors AS v ON v.id = i.vendor_id
               WHERE lower(i.status) NOT IN ('paid', 'closed')
               ORDER BY i.due_date, i.id"""
        ).fetchall()
        invoices = []
        for row in rows:
            invoice = dict(row)
            due = date.fromisoformat(str(invoice["due_date"]))
            invoice["shop_date"] = today.isoformat()
            invoice["overdue"] = due < today
            invoices.append(invoice)
        return invoices


@mcp.tool()
def get_lease(lease_id: int) -> dict[str, Any] | dict[str, str]:
    """Return lease and rent due-date details."""
    with _connect() as connection:
        row = connection.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        return _dict(row) or {"error": f"Lease {lease_id} was not found"}


@mcp.tool()
def get_cash_accounts() -> list[dict[str, Any]]:
    """Return current cash balances by account."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT name, balance, date FROM cash_accounts ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]


@mcp.tool()
def update_ticket_status(ticket_id: int, status: str) -> dict[str, Any]:
    """Update a ticket status to open, in_progress, or resolved."""
    allowed = {"open", "in_progress", "resolved"}
    normalized = status.strip().lower()
    if normalized not in allowed:
        return {"error": f"Status must be one of: {', '.join(sorted(allowed))}"}
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE tickets SET status = ? WHERE id = ?", (normalized, ticket_id)
        )
        if cursor.rowcount == 0:
            return {"error": f"Ticket {ticket_id} was not found"}
        return {"ticket_id": ticket_id, "status": normalized}


@mcp.tool()
def record_approved_invoice_payment(
    invoice_id: int, account: str, approved_by: str
) -> dict[str, Any]:
    """Record an invoice payment after human approval; reject unpaid cash shortages."""
    approver = approved_by.strip()
    if not approver:
        return {"error": "Human approval is required before recording payment"}

    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        today = _shop_date(connection)
        invoice = connection.execute(
            "SELECT id, amount, status FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if invoice is None:
            return {"error": f"Invoice {invoice_id} was not found"}
        if str(invoice["status"]).lower() in {"paid", "closed"}:
            return {"error": f"Invoice {invoice_id} is already paid or closed"}

        cash = connection.execute(
            "SELECT balance FROM cash_accounts WHERE name = ?", (account,)
        ).fetchone()
        if cash is None:
            return {"error": f"Cash account {account!r} was not found"}
        amount = float(invoice["amount"])
        balance = float(cash["balance"])
        if amount > balance:
            return {
                "error": "Insufficient cash; payment refused",
                "required": amount,
                "available": balance,
            }

        connection.execute(
            "UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
            (amount, today, account),
        )
        connection.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
        connection.execute(
            """INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by)
               VALUES ('invoice', ?, ?, ?, ?, ?)""",
            (invoice_id, amount, account, today, approver),
        )
        return {
            "invoice_id": invoice_id,
            "amount_paid": amount,
            "account": account,
            "remaining_balance": balance - amount,
            "paid_at": today,
            "approved_by": approver,
            "status": "paid",
        }


@mcp.tool()
def record_approved_purchase(
    amount: float, account: str, approved_by: str
) -> dict[str, Any]:
    """Record a human-approved purchase outflow; this does not place an order."""
    approver = approved_by.strip()
    account_name = account.strip()
    if not approver:
        return {"error": "Human approval is required before recording a purchase"}
    if not account_name:
        return {"error": "A cash account is required"}
    if amount <= 0:
        return {"error": "Purchase amount must be greater than zero"}

    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        today = _shop_date(connection)
        cash = connection.execute(
            "SELECT balance FROM cash_accounts WHERE name = ?", (account_name,)
        ).fetchone()
        if cash is None:
            return {"error": f"Cash account {account_name!r} was not found"}
        balance = float(cash["balance"])
        if amount > balance:
            return {
                "error": "Insufficient cash; purchase refused",
                "required": amount,
                "available": balance,
            }

        connection.execute(
            "UPDATE cash_accounts SET balance = balance - ?, date = ? WHERE name = ?",
            (amount, today, account_name),
        )
        connection.execute(
            """INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by)
               VALUES ('purchase', NULL, ?, ?, ?, ?)""",
            (amount, account_name, today, approver),
        )
        return {
            "kind": "purchase",
            "amount_paid": amount,
            "account": account_name,
            "remaining_balance": balance - amount,
            "paid_at": today,
            "approved_by": approver,
            "status": "recorded",
            "vendor_order_placed": False,
        }


if __name__ == "__main__":
    mcp.run()
