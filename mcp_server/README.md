# Campus Customs MCP Server

This FastMCP server provides database-backed tools for investigating Campus Customs tickets. It uses `../data/campus_customs_new.db`, the HW5 working copy. It opens that database when a tool is called; it does not create a second shop database.

## Read tools

### Ticket-focused

- `get_shop_date()` — reads `desk.date_today`, the shop's business date.
- `list_open_tickets()` — reads `desk`, `tickets`, `invoices`, and `leases`; returns open tickets with linked due-date facts and overdue flags based on the shop date.
- `get_ticket(ticket_id)` — reads `tickets` and linked `invoices`/`leases` details for one ticket.
- `check_order_stock(ticket_id)` — reads `tickets` and `inventory` to check a customer-order ticket's exact SKU, size, requested quantity, available quantity, and shortfall.
- `check_rent_due(ticket_id)` — reads `tickets`, `leases`, and `desk` to compare a rent-notice due date with the shop date.
- `evaluate_bulk_discount(ticket_id)` — reads `tickets`, `inventory`, and `pricing` to report stock and recorded cost/list-price arithmetic for a price-override ticket. No discount policy is stored; this tool does not approve or recommend a discount.

### Inventory, pricing, and vendors

- `get_inventory(sku, size=None)` — reads `inventory` for one SKU and optional size.
- `get_pricing(sku)` — reads `pricing` for the recorded unit cost and list price.
- `get_vendor(vendor_id)` — reads `vendors` and `invoices` for a known vendor's specialty, lead time, and unpaid-invoice count.
- `list_vendors()` — reads `vendors` and `invoices` to list recorded vendor IDs, specialties, lead times, unpaid-invoice counts, and shipment eligibility. It does not infer product/vendor suitability beyond recorded specialty.
- `check_vendor_shipping_eligibility(vendor_id)` — reads `vendors` and `invoices`; any open unpaid invoice blocks shipment.

### Accounting and facilities

- `get_invoice(invoice_id)` — reads `invoices` and linked `vendors` details.
- `list_unpaid_invoices()` — reads `invoices`, `vendors`, and `desk`; lists unpaid/open invoices and calculates overdue status using `desk.date_today`.
- `get_cash_accounts()` — reads `cash_accounts` balances.
- `get_lease(lease_id)` — reads `leases` rent and due-date details.

## Write tools

These server tools are available to authorized MCP clients but are intentionally not exposed to the five PydanticAI agents, which have read-only access.

- `update_ticket_status(ticket_id, status)` — writes `tickets.status`; accepts `open`, `in_progress`, or `resolved`.
- `record_approved_invoice_payment(invoice_id, account, approved_by)` — reads `desk`, `invoices`, and `cash_accounts`; writes `cash_accounts`, `invoices`, and `payments` in one transaction. It uses the shop date and refuses insufficient cash. A non-empty `approved_by` value is only an audit field, not proof of authenticated human approval; callers must obtain real human approval before use.
- `record_approved_purchase(amount, account, approved_by)` — reads `desk` and `cash_accounts`; writes `cash_accounts` and `payments` in one transaction, refuses insufficient cash, and records a generic purchase outflow. The database has no purchase-order table, so this does not place an order or contact a vendor. The approver value is an audit field, not authentication.

## Ticket-specific tools

- Ticket 101: `check_order_stock` checks the exact customer order against inventory.
- Ticket 102: `check_rent_due` compares the linked lease date to the shop date.
- Ticket 103: `evaluate_bulk_discount` reports recorded stock and pricing/margin facts without inventing a discount rule.

The server is configured through the workspace MCP setup to run against `../data/campus_customs_new.db`. Codex loads the project connection from the workspace-root `.codex/config.toml`; `.mcp.json` is retained for clients that use that format. Install the pinned dependencies from `requirements.txt` into `../.venv`.
