# Campus Customs Agent Team

## FastAPI dashboard routes

From the `HW5/backend/` directory, activate the project environment and run:

```sh
source ../.venv/bin/activate
uvicorn main:app --reload --port 8000
```

Install `requirements.txt` into `HW5/.venv` first. The API is intended for local development; Uvicorn binds to localhost by default. React development origins on ports 3000, 5172, and 5173 are allowed by CORS. The Vite dashboard runs at `http://localhost:5172` and calls this API directly at `http://localhost:8000`.

| Method and route | Purpose |
|---|---|
| `GET /api/health` | Health check. |
| `GET /api/tickets` | Return tickets 101–103 and their current status, including resolved tickets. |
| `POST /api/tickets/{ticket_id}/run` | Run Boss for one open ticket and return the structured report; the prompt explicitly excludes other tickets. |
| `POST /api/tickets/{ticket_id}/resolve` | Requires a human name and `confirmation: "RESOLVE TICKET"`; changes an open ticket to resolved through MCP after dashboard review. Agents never call it. |
| `GET /api/events?limit=100` | Return the newest persistent audit events for board refresh. |
| `GET /api/cash/checking` | Return the current checking balance through MCP. |
| `POST /api/approvals/payment` | Requires invoice ID, account, approver name, and `confirmation: "APPROVE PAYMENT"`; invokes the MCP payment tool, which performs the transactional cash/invoice/payment update and refuses insufficient cash. |
| `POST /api/approvals/purchase` | Requires amount, account, approver, and `confirmation: "APPROVE PURCHASE"`; records an approved cash outflow through MCP and refuses insufficient cash. The schema has no purchase-order table, so this does not place an order or contact a vendor. |
| `POST /api/database/reset` | Requires `confirmation: "RESET WORKING DATABASE"`; atomically restores `data/campus_customs_new.db` from the untouched original. Override the original path with `CAMPUS_CUSTOMS_ORIGINAL_DB` if needed. The audit log is retained. |

The payment, purchase, and reset confirmations make accidental calls less likely, but this is not user authentication. Do not expose the development server to a network or use it for real money; production needs authenticated, authorized approval and stronger operational controls. Purchase approval records the cash outflow only; it does not create a purchase order or contact a vendor.

The PydanticAI team has one module per role: `boss.py`, `inventory.py`, `accounting.py`, `facilities.py`, and `customer_service.py`. Their prompts live separately in `prompts/`, and shared data contracts are in `models.py`.

Every agent uses the OpenAI model `gpt-6-luna` through Portkey, authenticated with the `PORTKEY_API_KEY` in the project-root `.env`. This model is fixed for all roles in `config.py`; no agent reads a separate model setting. Never commit `.env` or print its contents.

Delegation is a complete directed peer network: every agent can delegate to each of the other four. An agent can ask multiple peers sequentially, inspect each response, and continue its work. Self-delegation and re-entry into an agent already on the current chain are blocked to prevent cycles; the chain is capped at six active agents. Each Boss run is limited to 40 model requests, 32 tool calls, and 50,000 total tokens across requests; these bounds help stop runaway loops and contain model usage.

Each role receives only the read-only MCP lookups relevant to its work. The team connects to `../mcp_server/server.py`, which reads `../data/campus_customs_new.db`. The backend is only an MCP client/tool adapter; agents do not open SQLite or use a parallel database route. Database facts come from the MCP server. Role-specific prompt files provide the operating procedure; `agent_factory.py` appends shared source-of-truth, business-date, vendor-block, cash/payment, communication, delegation, and reporting rules.

Additional ticket-support tools exposed by the MCP server are `list_vendors` (recorded specialty, lead days, unpaid-invoice count, and shipment eligibility) and `list_unpaid_invoices` (invoice/vendor facts with overdue state calculated using `desk.date_today`). These are read-only and use the same working database as the other tools.

## Audit trail

Every `run_boss()` call appends observable workflow events to `../output/audit_trail.json`, a persistent JSON array. It records run start/completion or failure; each agent start/completion/failure; delegation requests, results, and cycle/depth blocks; and every MCP tool call with its input and returned output or error. Records include UTC timestamps, a run ID, sequence number, and active agent chain. The writer preserves earlier runs and serializes concurrent appends. It does not store hidden model reasoning; it stores the task, tool evidence, delegation reports, and final structured reports needed to review what happened. Do not clear the file between runs.

Agents may recommend actions and prepare drafts, but they cannot update ticket statuses, record payments, reserve stock, place purchase orders, change prices, send email, or contact customers, vendors, or landlords. Payments remain subject to human approval, and customer messages are unsent drafts. Accounting and Facilities may prepare a payment recommendation but cannot pay. Inventory can discover recorded vendors through `list_vendors`, but it must not claim a vendor fits a product unless the recorded specialty supports that conclusion.

## Run

Install `backend/requirements.txt` into the HW5 virtual environment. The team loads `PORTKEY_API_KEY` from the project-root `.env` and routes OpenAI requests through Portkey using `gpt-6-luna` for every agent.

The main async entry point is `run_boss(task)` in `team.py`. Running a live agent makes model API requests; the credentials and model have not been tested with a live completion during implementation.
