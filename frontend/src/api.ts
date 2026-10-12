import type { AgentReport, AuditEvent, CashAccount, RunResponse, Ticket } from './types'

// In development, call FastAPI directly; its CORS policy allows the Vite origin.
const apiBase = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const payload = await response.json().catch(() => null) as { detail?: string } | null
  if (!response.ok) throw new Error(payload?.detail ?? `Request failed (${response.status})`)
  return payload as T
}

export const api = {
  tickets: () => request<Ticket[]>('/api/tickets'),
  cash: () => request<CashAccount>('/api/cash/checking'),
  events: () => request<{ events: AuditEvent[]; count: number }>('/api/events?limit=500'),
  runTicket: (ticketId: number) => request<RunResponse>(`/api/tickets/${ticketId}/run`, { method: 'POST' }),
  resolveTicket: (ticketId: number, resolvedBy: string) => request<{ ticket_id: number; status: string }>(
    `/api/tickets/${ticketId}/resolve`,
    { method: 'POST', body: JSON.stringify({ resolved_by: resolvedBy, confirmation: 'RESOLVE TICKET' }) },
  ),
  payInvoice: (invoiceId: number, approvedBy: string) => request<Record<string, unknown>>(
    '/api/approvals/payment',
    { method: 'POST', body: JSON.stringify({ invoice_id: invoiceId, account: 'checking', approved_by: approvedBy, confirmation: 'APPROVE PAYMENT' }) },
  ),
  approvePurchase: (amount: number, approvedBy: string) => request<Record<string, unknown>>(
    '/api/approvals/purchase',
    { method: 'POST', body: JSON.stringify({ amount, account: 'checking', approved_by: approvedBy, confirmation: 'APPROVE PURCHASE' }) },
  ),
}

export function reportNeedsApproval(report: AgentReport | null): boolean {
  return Boolean(report?.requires_human_approval)
}
