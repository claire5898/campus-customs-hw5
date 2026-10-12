# Campus Customs Agent Harness

This is the growing reference for the Campus Customs multi-agent system. It begins with the database structure and will be extended in later problems with agent responsibilities, tools, workflows, approval rules, and test evidence.

## Database tables and fields

Field names and types below reflect `data/campus_customs_new.db`.

### `desk`

- **Fields:** `date_today` (TEXT, required), `notes` (TEXT).
- **Why agents need it:** Provides the shop's current business date for decisions such as whether a ticket, rent notice, or invoice is overdue.

### `tickets`

- **Fields:** `id` (INTEGER, primary key), `type` (TEXT, required), `requester` (TEXT, required), `subject` (TEXT, required), `sku` (TEXT), `size` (TEXT), `qty` (INTEGER), `lease_id` (INTEGER, references `leases.id`), `invoice_id` (INTEGER, references `invoices.id`), `status` (TEXT, required), `notes` (TEXT), `created_at` (TEXT, required).
- **Why agents need it:** This is the work board; agents read open tickets, coordinate investigation and proposed actions, and update ticket status when work is resolved.

### `inventory`

- **Fields:** `sku` (TEXT, part of primary key), `name` (TEXT, required), `size` (TEXT, part of primary key), `qty` (INTEGER, required), `location` (TEXT, required). Composite primary key: (`sku`, `size`).
- **Why agents need it:** Lets agents check stock for the exact product and size, identify shortages, and avoid promising unavailable items.

### `pricing`

- **Fields:** `sku` (TEXT, primary key), `unit_cost` (REAL, required), `list_price` (REAL, required).
- **Why agents need it:** Supplies cost and list-price facts for margin checks and discount decisions; agents should use these values rather than guess.

### `vendors`

- **Fields:** `id` (INTEGER, primary key), `name` (TEXT, required), `specialty` (TEXT, required), `lead_days` (INTEGER, required).
- **Why agents need it:** Identifies suitable suppliers and provides their recorded lead times for restock estimates.

### `leases`

- **Fields:** `id` (INTEGER, primary key), `space_name` (TEXT, required), `landlord` (TEXT, required), `monthly_rent` (REAL, required), `next_due` (TEXT, required), `notes` (TEXT).
- **Why agents need it:** Gives Facilities and Accounting the lease, rent, and due-date details needed to handle rent tickets and prepare payments for approval.

### `cash_accounts`

- **Fields:** `name` (TEXT, primary key), `balance` (REAL, required), `date` (TEXT, required).
- **Why agents need it:** Shows available cash by account so a payment can be refused when funds are insufficient and balances never go negative.

### `payments`

- **Fields:** `id` (INTEGER, primary key), `kind` (TEXT, required), `ref_id` (INTEGER), `amount` (REAL, required), `account` (TEXT, required), `paid_at` (TEXT, required), `approved_by` (TEXT, required).
- **Why agents need it:** Records payments after human approval and provides an audit trail linking a payment to its kind of obligation and cash account.

### `invoices`

- **Fields:** `id` (INTEGER, primary key), `vendor_id` (INTEGER, required, references `vendors.id`), `amount` (REAL, required), `due_date` (TEXT, required), `status` (TEXT, required), `description` (TEXT).
- **Why agents need it:** Lets Accounting identify unpaid or overdue bills, prepare payment requests, and determine whether a vendor is eligible to ship new products.

## Relationships and implementation notes

- Enforced foreign keys: `invoices.vendor_id` → `vendors.id`; `tickets.lease_id` → `leases.id`; `tickets.invoice_id` → `invoices.id`.
- Logical links without declared foreign keys: `tickets.sku` and `tickets.size` correspond to `inventory`; `tickets.sku` corresponds to `pricing`; `payments.account` corresponds to `cash_accounts.name`.
- `payments.kind` and `payments.ref_id` identify the type and referenced record for a payment, but this polymorphic reference is not enforced by a foreign key.
- Use `desk.date_today` as the shop's date when calculating overdue status. Read vendor lead times from `vendors.lead_days`.
- Treat database values as the source of truth. Later sections will document agent/tool behavior and update this file as the assignment progresses.

## Problem 3 — Build the MCP Server

Implementation: `mcp_server/server.py`, using FastMCP and the working database `data/campus_customs_new.db`.

The server provides tools to read the shop date, open tickets, ticket details, inventory, pricing, vendor shipping eligibility and lead time, invoice details and overdue invoices, vendor list, lease details, and cash balances. It can update ticket status and record a human-approved invoice payment. Payment recording is transactional across `cash_accounts`, `invoices`, and `payments`, uses `desk.date_today`, and rejects an amount larger than the available account balance. Payment callers must obtain actual human approval before invoking the tool; the `approved_by` field is an audit value, not an authentication check. The agents use read-only MCP adapters; they do not access SQLite directly or bypass MCP.

The module opens the SQLite database only inside a tool call. It was not connected to the database or run while being authored, per the Problem 3 workflow instruction.

### Ticket-focused tools

| Tool | Tables read | Ticket(s) it helps unlock | Why it fits the ticket |
|---|---|---|---|
| `check_order_stock(ticket_id)` | `tickets`, `inventory` | 101 | Ticket 101 is a `customer_order` for 1 `CC-TEE-WHITE`, size S. The tool reads that ticket's exact SKU, size, and requested quantity, then checks the matching stock row and reports whether the order can be filled and any shortfall. |
| `check_rent_due(ticket_id)` | `tickets`, `leases`, `desk` | 102 | Ticket 102 is a `rent_notice` linked to lease 1. The tool returns that lease's recorded `monthly_rent` and `next_due`, then compares `next_due` with `desk.date_today` to classify the rent as overdue, due today, or upcoming. |
| `evaluate_bulk_discount(ticket_id)` | `tickets`, `inventory`, `pricing` | 103 | Ticket 103 is a `price_override` request for 20 `CC-HOOD-NAVY` hoodies, size M. The tool reports the matching stock and the database's `unit_cost` and `list_price`, plus arithmetic margin at list price; it does not invent a discount policy or approve a discount. |

These tools are read-only and provide ticket-specific evidence for the agents' decisions. They do not reserve stock, pay rent, or change pricing.

### Additional agent-support tools

| Tool | Tables read | Agent use |
|---|---|---|
| `list_vendors()` | `vendors`, `invoices` | Inventory can inspect the recorded vendor IDs, specialties, lead times, unpaid-invoice counts, and shipment eligibility. The tool does not assert a vendor is suitable for a product unless the recorded specialty supports that conclusion. |
| `list_unpaid_invoices()` | `invoices`, `vendors`, `desk` | Accounting can review all unpaid/open invoice records and their overdue status calculated against `desk.date_today`; vendor shipment/payment decisions can use the invoice and vendor IDs returned. |

## Problem 5 — PydanticAI Agent Team

Implemented in `backend/team.py`, with one module per agent, prompt files in `backend/prompts/`, and shared data types in `backend/models.py`:

| Agent | Responsibility | Model | MCP access / safety boundary |
|---|---|---|---|
| Boss | Read open tickets, delegate investigations, review findings, and recommend next steps. | `gpt-6-luna` via Portkey | `get_shop_date`, `list_open_tickets`, `get_ticket`; can delegate to each peer. No database writes or payment actions. |
| Inventory | Check exact item, size, quantity, stock, vendor lead-time, unpaid invoice, and shipment eligibility facts. | `gpt-6-luna` via Portkey | `get_shop_date`, `list_open_tickets`, `get_ticket`, `check_order_stock`, `get_inventory`, `get_vendor`, `list_vendors`, `check_vendor_shipping_eligibility`. Cannot order, reserve stock, contact vendors, or promise unconfirmed delivery. |
| Accounting | Check invoice records and due status, cash balances, pricing/margin facts, and payment readiness. | `gpt-6-luna` via Portkey | `get_shop_date`, `list_open_tickets`, `get_ticket`, `get_invoice`, `list_unpaid_invoices`, `get_cash_accounts`, `get_vendor`, `list_vendors`, `check_vendor_shipping_eligibility`, `get_pricing`, `evaluate_bulk_discount`. Recommendations only; cannot record payments. |
| Facilities | Check the linked lease and rent due dates; ask Accounting to check payment readiness. | `gpt-6-luna` via Portkey | `get_shop_date`, `list_open_tickets`, `get_ticket`, `check_rent_due`, `get_lease`, `get_cash_accounts`. Cannot pay rent or contact the landlord. |
| Customer Service | Draft helpful messages from verified facts without unsupported promises or internal financial disclosures. | `gpt-6-luna` via Portkey | `get_shop_date`, `get_ticket`, `check_order_stock`, `get_inventory`. Drafts only; cannot send messages. |

All agents use the same fixed model, `gpt-6-luna`, and the root `.env` `PORTKEY_API_KEY`; the model/provider setup is centralized in `backend/config.py`. Every database read goes through FastMCP and `data/campus_customs_new.db`. Although the MCP server exposes two write tools, none of the five agents receives them. `.env` is not committed.

### MCP tool catalog and database tables

This lists every FastMCP tool currently registered, including tools added to support the agent team. “Agent access” names the roles that receive the read-only tool in `backend/agent_factory.py`; the two write tools are intentionally unavailable to all agents.

| MCP tool | Tables used | Agent access / effect |
|---|---|---|
| `get_shop_date()` | `desk` (read) | All five agents; reads business date. |
| `list_open_tickets()` | `desk`, `tickets`, `invoices`, `leases` (read) | Boss, Inventory, Accounting, Facilities; reads open board and linked due facts. |
| `get_ticket(ticket_id)` | `tickets`, `invoices`, `leases` (read) | All five agents; reads one ticket and linked invoice/lease details. |
| `check_order_stock(ticket_id)` | `tickets`, `inventory` (read) | Inventory, Customer Service; checks ticket-specific SKU/size/quantity against stock. |
| `check_rent_due(ticket_id)` | `tickets`, `leases`, `desk` (read) | Facilities; compares linked due date to shop date. |
| `evaluate_bulk_discount(ticket_id)` | `tickets`, `inventory`, `pricing` (read) | Accounting; reports stock and list-price arithmetic, not an approved discount. |
| `get_inventory(sku, size?)` | `inventory` (read) | Inventory, Customer Service; looks up exact SKU and optional size. |
| `get_pricing(sku)` | `pricing` (read) | Accounting; reads recorded unit cost and list price. |
| `get_vendor(vendor_id)` | `vendors`, `invoices` (read) | Inventory, Accounting; reads a known vendor, lead time, specialty, and unpaid-invoice count. |
| `list_vendors()` | `vendors`, `invoices` (read) | Inventory, Accounting; newly added vendor discovery from recorded rows, with lead times and shipment eligibility facts. Does not infer product-vendor fit beyond recorded specialty. |
| `check_vendor_shipping_eligibility(vendor_id)` | `vendors`, `invoices` (read) | Inventory, Accounting; blocks shipment eligibility when unpaid invoices remain. |
| `get_invoice(invoice_id)` | `invoices`, `vendors` (read) | Accounting; reads one invoice and linked vendor details. |
| `list_unpaid_invoices()` | `invoices`, `vendors`, `desk` (read) | Accounting; newly added list of unpaid invoices, with overdue state calculated from `desk.date_today`. |
| `get_lease(lease_id)` | `leases` (read) | Facilities; reads lease and rent terms. |
| `get_cash_accounts()` | `cash_accounts` (read) | Accounting, Facilities; reads current balances for payment readiness only. |
| `update_ticket_status(ticket_id, status)` | `tickets` (write) | No agent access; server tool can update status, but agents must only recommend and report. |
| `record_approved_invoice_payment(invoice_id, account, approved_by)` | `desk` (read); `invoices`, `cash_accounts`, `payments` (write) | No agent access; server tool records an approved payment transactionally and refuses insufficient cash. The `approved_by` value alone is not authentication or proof of approval. |
| `record_approved_purchase(amount, account, approved_by)` | `desk`, `cash_accounts` (read); `cash_accounts`, `payments` (write) | No agent access; records a human-approved purchase cash outflow and refuses insufficient cash. It does not create a purchase order or contact a vendor. |

### Safety and run limits

**Implemented in this homework:** agents receive role-scoped read-only database tools; customer messages are drafts and are never sent; vendor/landlord contact, purchase orders, stock reservations, ticket updates, price changes, and payment writes are not available to agents. The human-approved purchase route records only a generic cash outflow because the schema has no purchase-order table; it does not place an order. Due dates use the shop's `desk.date_today`; vendors with unpaid invoices are ineligible to ship; no incoming revenue or negative cash is assumed. The audit trail preserves tool inputs/outputs, delegation reports, and final agent reports.

**Additional controls before a real business deployment:** authenticate and authorize each human approver outside the model; require a separate human confirmation step for payment/order/status changes; enforce least-privilege access per employee and agent; validate tool arguments and enforce idempotency/duplicate-payment protection server-side; protect customer and financial data with encryption, retention limits, access logs, and redaction; require human review before any customer message is sent; add transaction limits, anomaly alerts, and a tested rollback/reconciliation procedure. The current `approved_by` parameter is only an audit field, not a secure approval mechanism.

**Usage bounds:** one Boss run is capped at 40 model requests, 32 tool calls, and 50,000 total input-plus-output tokens; delegation is limited to six active agents, with self-delegation and active-chain cycles blocked. These runtime limits bound loops and model usage; a real deployment should additionally set provider-side spend/rate limits and monitor per-run usage.

### Agent system prompts

Each complete role prompt is stored in its own file:

- Boss — `backend/prompts/boss.md`
- Inventory — `backend/prompts/inventory.md`
- Accounting — `backend/prompts/accounting.md`
- Facilities — `backend/prompts/facilities.md`
- Customer Service — `backend/prompts/customer_service.md`

The role prompts are detailed operational instructions in their respective files; the shared prompt policy is in `backend/agent_factory.py`. All agents use MCP results as the factual source, use `desk.date_today` (not the computer date) for due/overdue decisions, and use `vendors.lead_days` for recorded restock estimates. A vendor with an open unpaid invoice cannot ship. Cash only goes out; no revenue may be assumed; insufficient cash must stop a payment recommendation. Human approval is required for all payments. Agents cannot write to the database, reserve stock, order, change prices, send messages, or claim work complete. They report unknowns rather than filling gaps.

**Delegation and reporting:** give a peer a focused ticket-specific evidence question, inspect the returned report, cross-check consequential/conflicting facts, then synthesize verified facts, recommendation, approval need, draft (if relevant), and unknowns. Do not repeat an unanswered delegation. All five agents have directed delegation tools to each of the other four (complete peer connectivity). Self-delegation and re-entry into an agent already active on the current chain are blocked; the chain is limited to six active agents and the Boss run is capped at 40 model requests and 32 tool calls.

**Audit trail:** Each `run_boss()` execution appends JSON records to `output/audit_trail.json` without clearing earlier runs. Events include run/agent starts, completions and failures; delegation requests and returned reports; cycle/depth blocks; and MCP tool inputs, outputs, and errors. Each event includes a UTC timestamp, run ID, sequence, and agent chain. This captures observable workflow evidence and reports, not hidden model reasoning.

## Problem 4 — Add the MCP Server to Vibe Coder and Test Each Tool

Registered the server as the project-scoped `campus-customs` MCP server in the workspace-root `.codex/config.toml`, which Codex reads for MCP configuration. It launches `HW5/mcp_server/server.py` using `HW5/.venv` and sets `CAMPUS_CUSTOMS_DB` to `HW5/data/campus_customs_new.db`. The workspace-root `.mcp.json` is retained as requested for MCP clients that use JSON configuration; it is not Codex's active config format. The workspace is trusted in Codex.

### Tool test results

All 18 registered tools were discovered and called successfully through an MCP client. Tests used a disposable copy of the working database, so ticket-status, payment, and purchase writes did not affect `data/campus_customs_new.db`.

- Passed: `get_shop_date`, `check_order_stock`, `check_rent_due`, `evaluate_bulk_discount`, `list_open_tickets`, `get_ticket`, `get_inventory`, `get_pricing`, `get_vendor`, `list_vendors`, `check_vendor_shipping_eligibility`, `get_invoice`, `list_unpaid_invoices`, `get_lease`, `get_cash_accounts`, and `update_ticket_status`.
- Passed: `record_approved_invoice_payment` refused a payment when the test account had insufficient cash.
- Passed: `record_approved_invoice_payment` recorded an approved invoice payment and updated the invoice, payment ledger, and cash balance on the disposable database.
- Passed: `record_approved_purchase` refused an outflow exceeding available cash and recorded an approved purchase outflow in the payment ledger on the disposable database; it does not place a vendor order.

The tools were exercised using the MCP client. Codex's `mcp list` command reads the trusted project config and lists `campus-customs` as enabled. The VS Code panel itself was not separately refreshed or visually inspected after adding the config.

## Problem 7 — Backend Routes

FastAPI app: `backend/main.py`. Base URL for local development: `http://localhost:8000`.

| Method and URL | What it does |
|---|---|
| `GET http://localhost:8000/api/health` | Returns API health status. |
| `GET http://localhost:8000/api/tickets` | Returns tickets 101–103, including each ticket's current status. |
| `POST http://localhost:8000/api/tickets/{ticket_id}/run` | Runs Boss and only the needed specialists for the specified open ticket; returns its structured report. |
| `POST http://localhost:8000/api/tickets/{ticket_id}/resolve` | After human review and exact confirmation, marks an open ticket resolved through MCP; agents do not change ticket status. |
| `GET http://localhost:8000/api/events?limit=100` | Returns recent persistent audit events, including agent reports and MCP tool activity, for dashboard refresh. |
| `GET http://localhost:8000/api/cash/checking` | Returns the current checking-account record from the MCP server. |
| `POST http://localhost:8000/api/approvals/payment` | After explicit human confirmation, invokes the MCP payment tool to update cash, invoice, and payment records transactionally; insufficient cash is refused. |
| `POST http://localhost:8000/api/approvals/purchase` | Requires explicit human confirmation and records the approved purchase cash outflow through MCP; insufficient cash is refused. It does not place a vendor order because purchase orders are not modeled. |
| `POST http://localhost:8000/api/database/reset` | After the exact reset confirmation, restores the working database from the untouched original and preserves the audit log. |

Start from `HW5/backend/` with `source ../.venv/bin/activate` followed by `uvicorn main:app --reload --port 8000`. Payment/reset confirmation is not authentication; this app is for local homework use, not real financial operations.

**Verification:** The live health, ticket, checking-balance, events, and OpenAPI endpoints responded at `localhost:8000`; tickets 101–103 were open and checking remained `$3,400`. Backend/agent tests and the MCP suite passed. Three earlier route-unit-test runs emitted simulated purchase-approval audit events while the MCP call was mocked; no money moved. They remain in the append-only audit file with a later `test_artifact_explanation` entry, and tests now mock the audit writer to prevent recurrence. The live agent-run route has not yet been exercised against the model.

## Problem 8 — Agent Dashboard

`frontend/` is a React + Vite + TypeScript single-page dashboard. It lists all three tickets; selecting an open ticket can start a ticket-scoped run. While the request is running, the UI polls `GET /api/events` and displays agent starts/completions, delegation, MCP tool names/results, and each agent's latest summary. It refreshes checking balance and ticket status after writes. Human payment/purchase dialogs require a typed confirmation; a purchase records cash only, not a vendor order. After a run completes, a human can explicitly resolve the ticket; completion alone never changes status. The frontend calls FastAPI directly at `http://localhost:8000`; Vite runs at `http://localhost:5172` and opens the page on start. CORS permits localhost ports 3000, 5172, and 5173.

Local start: from `HW5/frontend/`, run `npm install` and `npm run dev`. Start the backend separately from `HW5/backend/`. Design rationale is in `output/design.md`. Verification: the Vite production build and 13 backend/agent tests passed. A live browser check showed all three open tickets, five agents, and the $3,400 checking balance. Live runs on ticket 101 and, after reset, tickets 101–103 appended agent events; the audit endpoint returned HTTP 200. The UTF-8-safe append implementation preserves prior events and has a Unicode regression test. No payment, purchase, or resolution was submitted.

## Problem 9 — Resolve the Tickets

Reset `data/campus_customs_new.db` from the configured original before the full run; the reset route verified the copied-file checksum. Starting checking was `$3,400` on shop date `2026-08-31`. Ran the live agent team on tickets 101, 102, and 103; each run appended agent, delegation, and MCP evidence to `output/audit_trail.json`.

- **Ticket 101:** 0 of 1 requested CC-TEE-WHITE size S is available. Vendor 1 is ineligible to ship while open invoice 501 ($840, due 2026-08-28) remains unpaid. Lead time is an estimate only. Boss recommends human review of invoice payment and keeping the ticket open until eligibility and stock are rechecked.
- **Ticket 102:** $2,400 rent is due `2026-09-02`, two days after the shop date, and is not overdue. Checking was `$3,400`; whether rent was already paid/approved and the timing of other obligations are unknown. Boss recommends confirming records and rechecking cash; no landlord contact or payment.
- **Ticket 103:** 8 of 20 requested CC-HOOD-NAVY size M are available (short 12); no discount rule/approval is recorded. Vendor is blocked by an unpaid invoice and its lead-time estimate is not a commitment. Boss recommends human pricing review and verified fulfillment before a commitment.

After the three runs, Claire used the human-confirmed resolution route to mark tickets 101–103 resolved for the assignment. Checking remained `$3,400`; no payment, purchase, customer/vendor contact, or fulfillment was recorded. The resolution is status-only and should not be read as proof that ticket 101's tee or ticket 103's hoodies were supplied, that invoice 501 or rent was paid, or that customers/landlord were notified. Actual agent, delegation, and MCP tool details are recorded in `output/desk_tickets.html` for comparison with the original EXPECTED plans.

**Append-only audit evidence:** The three live Problem 9 agent runs are already appended in `output/audit_trail.json`; they were not replayed or duplicated while documenting this section. Ticket 101 is run `c1276cd2-9dba-41cc-bd17-2b661b33bac7` (sequences 43–76), ticket 102 is run `6afd1442-5450-466b-aaf8-cde1564c741d` (77–114), and ticket 103 is run `6b348a00-efa1-462b-8113-f9032c0128fc` (115–158). Each range contains the run start/completion, agent starts/completions, delegation requests/results (including cycle-block records where applicable), and MCP tool start/completion records. Human status-only resolutions follow at sequences 159–161. Earlier `human_purchase_approval_*` entries at sequences 1–6 are mocked route-test artifacts, not real purchases or cash changes; they are retained as part of the append-only history and identified by the existing `test_artifact_explanation` event. The audit currently parses as JSON and contains 161 events.

Structured ticket outcomes and the exact human status approvals are also summarized in `output/resolved_tickets.json`. The cash reconciliation in the Cash tab of `output/desk_tickets.html` records $3,400 starting balance, $0 change for each ticket, and $3,400 ending balance, matching `cash_accounts` in the working database.

## Problem 10 — Reflection

Claire's reflection is saved in the Reflection tab of `output/desk_tickets.html`. It evaluates the agents using database accuracy, task-focused delegation, safety, efficiency, and whether status resolution matches real outcomes. It compares the EXPECTED and ACTUAL sections for tickets 101–103 and cites the Cash tab ($3,400 starting balance, $0 per-ticket change, $3,400 ending balance) as evidence. It also discusses when one agent might be simpler, three issue types the current read tools can investigate, and three problems requiring additional purchasing, refund/return, or rent-payment/contact capabilities. The reflection remains editable in-browser and autosaves via local storage.
