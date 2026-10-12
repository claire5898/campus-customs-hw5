"""Shared PydanticAI agent construction and role-scoped MCP tool policy."""

from __future__ import annotations

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import Model

from .config import make_model
from .mcp_tools import MCP_READ_FUNCTIONS
from .models import AgentReport, TeamRuntime


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
TEAM_POLICY = """Shared Campus Customs rules:
Source of truth and time:
- Treat MCP results from the working database as authoritative. Do not invent or silently assume customer, vendor, stock, price, invoice, lease, payment, cash, or policy facts.
- For every due/overdue decision, read the shop date from desk.date_today using get_shop_date (or a tool output that explicitly includes it). Never substitute the computer's current date.
- For any restock estimate, use vendors.lead_days returned by get_vendor. Do not promise delivery dates; the recorded lead time is an estimate, not a shipment confirmation.
- Distinguish recorded facts from arithmetic, recommendations, and unknowns. If a required record or field is unavailable, say what is missing and ask a peer with the relevant scope.

Shop operating and safety rules:
- A vendor with an open unpaid invoice must not ship new product. Check shipping eligibility; do not treat a vendor record or lead time alone as permission to ship.
- Cash only leaves the shop in this assignment; no revenue or incoming cash is modeled. Never assume future income, transfer funds, or recommend a negative balance.
- Every payment requires actual human approval. Agents are read-only: do not make/record payments, change ticket status, reserve stock, place purchase orders, change prices, or claim an action was completed. A name in an approval field is not proof of approval.
- Do not email/message customers, call/contact vendors or landlords, or send purchase orders. Customer text may only be drafted for a human; vendor/landlord communication is not performed.
- Do not expose internal cash, margin, invoice, or vendor details in customer-facing drafts unless the requester explicitly needs them; normally keep such details internal.

Delegation and reporting:
- You may delegate to any peer except yourself. Give each peer a focused question, the ticket ID, and only the context needed; request database-backed facts and uncertainties.
- Inspect each returned report. Cross-check conflicting or consequential facts with your own MCP tools where available. Continue with a different relevant peer when needed, but do not repeat an unanswered delegation or claim an unverified peer statement as database fact.
- Keep recommendations separate from completed actions and approval decisions. Never mark a ticket resolved; a human or later authorized workflow owns that action.
- Return a concise, useful AgentReport: identify your role, summarize the ticket/work, list verified facts with their source/context, state a specific recommendation, include a customer draft only when useful, set requires_human_approval when an action needs a person, and list material unknowns/blockers.
- If a tool errors, required data is missing, or a delegation/run limit is reached, stop that line of work and report the limitation rather than guessing.
"""

READ_TOOLS: dict[str, tuple[str, ...]] = {
    "Boss": ("get_shop_date", "list_open_tickets", "get_ticket"),
    "Inventory": (
        "get_shop_date", "list_open_tickets", "get_ticket", "check_order_stock",
        "get_inventory", "get_vendor", "list_vendors", "check_vendor_shipping_eligibility",
    ),
    "Accounting": (
        "get_shop_date", "list_open_tickets", "get_ticket", "get_invoice",
        "get_cash_accounts", "get_vendor", "check_vendor_shipping_eligibility",
        "list_vendors", "list_unpaid_invoices", "get_pricing", "evaluate_bulk_discount",
    ),
    "Facilities": (
        "get_shop_date", "list_open_tickets", "get_ticket", "check_rent_due",
        "get_lease", "get_cash_accounts",
    ),
    "Customer Service": (
        "get_shop_date", "get_ticket", "check_order_stock", "get_inventory",
    ),
}


def prompt_for(role: str) -> str:
    """Read an agent's separately maintained prompt file."""
    prompt_path = PROMPT_DIR / f"{role.lower().replace(' ', '_')}.md"
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file missing for {role}: {prompt_path}")
    return f"{prompt_path.read_text(encoding='utf-8').strip()}\n\n{TEAM_POLICY}"


def create_role_agent(role: str, model: Model | str | None = None) -> Agent[TeamRuntime, AgentReport]:
    """Create one role agent with its file-based prompt and read-only tools."""
    if role not in READ_TOOLS:
        raise ValueError(f"Unknown Campus Customs agent role: {role}")
    agent = Agent(
        model or make_model(),
        name=role.lower().replace(" ", "_"),
        deps_type=TeamRuntime,
        output_type=AgentReport,
        instructions=prompt_for(role),
    )
    for tool_name in READ_TOOLS[role]:
        agent.tool(MCP_READ_FUNCTIONS[tool_name])
    return agent
