export type Ticket = {
  ticket_id: number
  type: string
  requester: string
  subject: string
  status: string
  notes: string | null
  sku?: string | null
  size?: string | null
  qty?: number | null
  invoice_id?: number | null
  invoice_amount?: number | null
  invoice_due_date?: string | null
  invoice_status?: string | null
  lease_next_due?: string | null
  monthly_rent?: number | null
  landlord?: string | null
  space_name?: string | null
  [key: string]: unknown
}

export type AgentReport = {
  agent: string
  summary: string
  verified_facts: string[]
  recommendations: string[]
  customer_message_draft?: string | null
  requires_human_approval: boolean
  unknowns: string[]
}

export type AuditEvent = {
  sequence: number
  timestamp_utc: string
  run_id: string
  event: string
  agent?: string
  agent_chain?: string[]
  from_agent?: string
  to_agent?: string
  task?: string
  tool_name?: string
  tool_input?: Record<string, unknown>
  tool_output?: unknown
  report?: AgentReport
  error?: string
  error_type?: string
  [key: string]: unknown
}

export type CashAccount = { name: string; balance: number; date: string }
export type RunResponse = { ticket_id: number; report: AgentReport }
