"""Local FastAPI routes for the Campus Customs dashboard."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# Support the requested command when the shell's working directory is backend/:
# uvicorn main:app --reload --port 8000
BACKEND_DIR = Path(__file__).resolve().parent
HW5_DIR = BACKEND_DIR.parent
if str(HW5_DIR) not in sys.path:
    sys.path.insert(0, str(HW5_DIR))

from backend.audit import AuditTrail  # noqa: E402
from backend.mcp_tools import (  # noqa: E402
    WORKING_DATABASE,
    mcp_result_to_value,
    open_mcp_session,
)
from backend.team import run_boss  # noqa: E402


ORIGINAL_DATABASE = Path(
    os.environ.get(
        "CAMPUS_CUSTOMS_ORIGINAL_DB",
        str(HW5_DIR / "data" / "campus_customs.db"),
    )
).expanduser().resolve()
TICKET_IDS = (101, 102, 103)

app = FastAPI(
    title="Campus Customs API",
    description="Dashboard routes for ticket status, agent runs, audit events, approvals, and reset.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5172", "http://127.0.0.1:5172",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Serialize live agent runs and state-changing operations in this local demo.
_operation_lock = asyncio.Lock()


class PaymentApproval(BaseModel):
    invoice_id: int = Field(gt=0)
    account: str = Field(min_length=1, max_length=80)
    approved_by: str = Field(min_length=1, max_length=120)
    confirmation: Literal["APPROVE PAYMENT"]


class PurchaseApproval(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    account: str = Field(min_length=1, max_length=80)
    approved_by: str = Field(min_length=1, max_length=120)
    confirmation: Literal["APPROVE PURCHASE"]


class TicketResolution(BaseModel):
    resolved_by: str = Field(min_length=1, max_length=120)
    confirmation: Literal["RESOLVE TICKET"]


class ResetRequest(BaseModel):
    confirmation: Literal["RESET WORKING DATABASE"]


async def _mcp_call(tool_name: str, arguments: dict | None = None):
    """Call the FastMCP server; routes do not query SQLite directly."""
    async with open_mcp_session() as session:
        result = await session.call_tool(tool_name, arguments or {})
    value = mcp_result_to_value(result)
    if getattr(result, "isError", False):
        raise HTTPException(status_code=502, detail=f"MCP tool {tool_name} failed")
    if isinstance(value, dict) and "error" in value:
        message = str(value["error"])
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status_code=status, detail=message)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "campus-customs-api"}


@app.get("/api/tickets")
async def get_tickets() -> list[dict]:
    """Return tickets 101–103 and their current status, including resolved tickets."""
    tickets = []
    for ticket_id in TICKET_IDS:
        ticket = await _mcp_call("get_ticket", {"ticket_id": ticket_id})
        ticket["ticket_id"] = ticket.pop("id")
        tickets.append(ticket)
    return tickets


@app.post("/api/tickets/{ticket_id}/run")
async def run_ticket_agents(ticket_id: int) -> dict:
    """Run Boss and only the needed specialists for one open ticket."""
    if ticket_id not in TICKET_IDS:
        raise HTTPException(status_code=404, detail="Only tickets 101, 102, and 103 are supported")
    async with _operation_lock:
        ticket = await _mcp_call("get_ticket", {"ticket_id": ticket_id})
        if str(ticket.get("status", "")).lower() != "open":
            raise HTTPException(status_code=409, detail="Only open tickets can be run")
        task = (
            f"Investigate ONLY open Campus Customs ticket {ticket_id}. Ticket data: {ticket}. "
            "Use the MCP server as the source of truth. Delegate only to specialists needed "
            "for this ticket; do not investigate the other tickets. Return evidence, a "
            "recommendation, approval needs, and unknowns. Do not make payments, write to "
            "the database, contact anyone, or claim an action is complete."
        )
        try:
            report = await run_boss(task)
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Agent run failed: {type(error).__name__}") from error
        return {"ticket_id": ticket_id, "report": report.model_dump(mode="json")}


@app.post("/api/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, request: TicketResolution) -> dict:
    """Resolve only after an explicit human dashboard action and confirmation."""
    if ticket_id not in TICKET_IDS:
        raise HTTPException(status_code=404, detail="Only tickets 101, 102, and 103 are supported")
    resolver = request.resolved_by.strip()
    if not resolver:
        raise HTTPException(status_code=422, detail="A resolver name is required")
    async with _operation_lock:
        ticket = await _mcp_call("get_ticket", {"ticket_id": ticket_id})
        if str(ticket.get("status", "")).lower() != "open":
            raise HTTPException(status_code=409, detail="Only open tickets can be resolved")
        result = await _mcp_call("update_ticket_status", {"ticket_id": ticket_id, "status": "resolved"})
        AuditTrail().append(
            "human_ticket_resolved",
            ticket_id=ticket_id,
            resolved_by=resolver,
            confirmation=request.confirmation,
            result=result,
        )
        return result


@app.get("/api/events")
async def get_recent_events(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """Return recent persistent agent/tool events for dashboard refresh."""
    try:
        events = AuditTrail().read_recent(limit)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Could not read the audit trail") from error
    return {"events": events, "count": len(events)}


@app.get("/api/cash/checking")
async def get_checking_balance() -> dict:
    accounts = await _mcp_call("get_cash_accounts")
    checking = next(
        (account for account in accounts if str(account.get("name", "")).lower() == "checking"),
        None,
    )
    if checking is None:
        raise HTTPException(status_code=404, detail="Checking account was not found")
    return checking


@app.post("/api/approvals/payment")
async def approve_invoice_payment(request: PaymentApproval) -> dict:
    """After explicit dashboard confirmation, ask MCP to atomically pay an invoice."""
    if not request.approved_by.strip() or not request.account.strip():
        raise HTTPException(status_code=422, detail="Approver and account are required")
    async with _operation_lock:
        audit = AuditTrail()
        audit.append(
            "human_payment_approval_submitted",
            invoice_id=request.invoice_id,
            account=request.account,
            approved_by=request.approved_by.strip(),
        )
        try:
            result = await _mcp_call(
                "record_approved_invoice_payment",
                {
                    "invoice_id": request.invoice_id,
                    "account": request.account.strip(),
                    "approved_by": request.approved_by.strip(),
                },
            )
        except HTTPException as error:
            audit.append(
                "human_payment_approval_failed",
                invoice_id=request.invoice_id,
                account=request.account.strip(),
                approved_by=request.approved_by.strip(),
                error=error.detail,
            )
            raise
        audit.append("human_payment_approval_completed", payment_result=result)
        return result


@app.post("/api/approvals/purchase")
async def approve_purchase(request: PurchaseApproval) -> dict:
    """After explicit human confirmation, record a purchase cash outflow via MCP.

    The database has no purchase-order table; this records the expense in the
    payments ledger and deliberately does not contact a vendor or place an order.
    """
    if not request.approved_by.strip() or not request.account.strip():
        raise HTTPException(status_code=422, detail="Approver and account are required")
    async with _operation_lock:
        audit = AuditTrail()
        audit.append(
            "human_purchase_approval_submitted",
            amount=request.amount,
            account=request.account.strip(),
            approved_by=request.approved_by.strip(),
        )
        try:
            result = await _mcp_call(
                "record_approved_purchase",
                {
                    "amount": request.amount,
                    "account": request.account.strip(),
                    "approved_by": request.approved_by.strip(),
                },
            )
        except HTTPException as error:
            audit.append(
                "human_purchase_approval_failed",
                amount=request.amount,
                account=request.account.strip(),
                approved_by=request.approved_by.strip(),
                error=error.detail,
            )
            raise
        audit.append("human_purchase_approval_completed", purchase_result=result)
        return result


@app.post("/api/database/reset")
async def reset_working_database(request: ResetRequest) -> dict[str, str]:
    """Restore the working copy from the configured original after explicit confirmation."""
    source = ORIGINAL_DATABASE
    destination = WORKING_DATABASE.resolve()
    if source == destination:
        raise HTTPException(status_code=400, detail="Original and working database paths must differ")
    if not source.is_file():
        raise HTTPException(status_code=404, detail=f"Original database not found: {source}")

    async with _operation_lock:
        temporary_path: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=".campus_customs_reset_",
                suffix=".db",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            shutil.copyfile(source, temporary_path)
            with temporary_path.open("rb") as restored:
                os.fsync(restored.fileno())
            source_hash = _sha256(source)
            restored_hash = _sha256(temporary_path)
            if source_hash != restored_hash:
                raise OSError("Reset copy checksum did not match the original")
            os.replace(temporary_path, destination)
            temporary_path = None
            AuditTrail().append(
                "working_database_reset",
                source=str(source),
                destination=str(destination),
                sha256=restored_hash,
                confirmation=request.confirmation,
            )
            return {"status": "reset", "database": str(destination), "sha256": restored_hash}
        except OSError as error:
            raise HTTPException(status_code=500, detail="Could not reset the working database") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
