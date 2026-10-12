import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Activity, BadgeCheck, Banknote, Check, CheckCircle2,
  ChevronRight, CircleHelp, Clock3, CreditCard, Heart, Inbox, LoaderCircle, LockKeyhole,
  MessageCircle, RotateCw, Send, ShieldCheck, Sparkles, WalletCards, X,
} from 'lucide-react'
import { api, reportNeedsApproval } from './api'
import type { AgentReport, AuditEvent, CashAccount, Ticket } from './types'

const agentNames = ['Boss', 'Inventory', 'Accounting', 'Facilities', 'Customer Service']
type ApprovalKind = 'payment' | 'purchase' | 'resolve' | null

function titleCase(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function money(value: number | null | undefined): string {
  return typeof value === 'number'
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(value)
    : '—'
}

function shortTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(date)
}

function compact(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === undefined || value === null) return ''
  const serialized = JSON.stringify(value)
  return serialized.length > 240 ? `${serialized.slice(0, 237)}…` : serialized
}

function eventHeadline(event: AuditEvent): string {
  if (event.event === 'agent_started') return `${event.agent ?? 'Agent'} started working`
  if (event.event === 'agent_completed') return event.report?.summary ?? `${event.agent ?? 'Agent'} shared findings`
  if (event.event === 'agent_failed' || event.event === 'run_failed') return `${event.agent ?? 'Agent'} hit an issue: ${event.error ?? event.error_type ?? 'run failed'}`
  if (event.event === 'delegation_started') return `${event.from_agent ?? 'An agent'} asked ${event.to_agent ?? 'a teammate'} to investigate`
  if (event.event === 'delegation_completed') return `${event.to_agent ?? 'Teammate'} returned a focused finding`
  if (event.event === 'mcp_tool_started') return `${event.agent ?? 'Agent'} is checking ${titleCase(event.tool_name ?? 'a database tool')}`
  if (event.event === 'mcp_tool_completed') return `${event.agent ?? 'Agent'} checked ${titleCase(event.tool_name ?? 'a database tool')}`
  if (event.event === 'run_started') return 'The team started its ticket review'
  if (event.event === 'run_completed') return 'The team finished its review'
  return titleCase(event.event)
}

function eventIcon(event: AuditEvent) {
  if (event.event.includes('failed')) return <CircleHelp size={15} />
  if (event.event === 'agent_completed' || event.event === 'run_completed') return <CheckCircle2 size={15} />
  if (event.event.startsWith('mcp_tool')) return <Activity size={15} />
  if (event.event.startsWith('delegation')) return <Send size={15} />
  return <Sparkles size={15} />
}

function App() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [cash, setCash] = useState<CashAccount | null>(null)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [report, setReport] = useState<AgentReport | null>(null)
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [apiOnline, setApiOnline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [approvalKind, setApprovalKind] = useState<ApprovalKind>(null)
  const [approver, setApprover] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [purchaseAmount, setPurchaseAmount] = useState('')
  const [runBaseline, setRunBaseline] = useState<number | null>(null)

  const selectedTicket = tickets.find((ticket) => ticket.ticket_id === selectedId) ?? null
  const runEvents = useMemo(
    () => runBaseline === null ? [] : events.filter((event) => event.sequence > runBaseline),
    [events, runBaseline],
  )
  const approvalRequired = reportNeedsApproval(report)

  const refresh = useCallback(async () => {
    const [ticketResult, cashResult, eventResult] = await Promise.allSettled([
      api.tickets(), api.cash(), api.events(),
    ])
    if (ticketResult.status === 'fulfilled') {
      setTickets(ticketResult.value)
      setSelectedId((current) => current ?? ticketResult.value[0]?.ticket_id ?? null)
    }
    if (cashResult.status === 'fulfilled') setCash(cashResult.value)
    if (eventResult.status === 'fulfilled') setEvents(eventResult.value.events)
    const rejected = [ticketResult, cashResult, eventResult].find((result) => result.status === 'rejected')
    if (rejected?.status === 'rejected') {
      setApiOnline(false)
      setError(rejected.reason instanceof Error ? rejected.reason.message : 'Could not reach the dashboard API.')
    } else {
      setApiOnline(true)
      setError('')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, running ? 1200 : 5000)
    return () => window.clearInterval(timer)
  }, [refresh, running])

  const closeApproval = () => {
    setApprovalKind(null)
    setApprover('')
    setConfirmation('')
    setPurchaseAmount('')
  }

  const startRun = async () => {
    if (!selectedTicket || running || selectedTicket.status !== 'open') return
    setError('')
    setReport(null)
    try {
      const latest = await api.events()
      const baseline = Math.max(0, ...latest.events.map((event) => event.sequence))
      setRunBaseline(baseline)
      setRunning(true)
      const result = await api.runTicket(selectedTicket.ticket_id)
      setReport(result.report)
      const updatedEvents = await api.events()
      setEvents(updatedEvents.events)
      setNotice(`Ticket #${selectedTicket.ticket_id} review is complete. Please review before resolving.`)
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'The agent team could not run.')
      try {
        const updatedEvents = await api.events()
        setEvents(updatedEvents.events)
      } catch { /* Keep the original run error visible. */ }
    } finally {
      setRunning(false)
      void refresh()
    }
  }

  const submitApproval = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!approvalKind || !approver.trim() || busy) return
    const requiredText = approvalKind === 'payment' ? 'APPROVE PAYMENT'
      : approvalKind === 'purchase' ? 'APPROVE PURCHASE' : 'RESOLVE TICKET'
    if (confirmation.trim() !== requiredText) return
    setBusy(true)
    setError('')
    try {
      if (approvalKind === 'payment') {
        if (!selectedTicket?.invoice_id) throw new Error('This ticket has no linked invoice to pay.')
        await api.payInvoice(selectedTicket.invoice_id, approver.trim())
        setNotice('Payment recorded. The checking balance has been refreshed.')
      } else if (approvalKind === 'purchase') {
        const amount = Number(purchaseAmount)
        if (!Number.isFinite(amount) || amount <= 0) throw new Error('Enter a purchase amount greater than zero.')
        await api.approvePurchase(amount, approver.trim())
        setNotice('Purchase cash outflow recorded. No vendor order was placed.')
      } else if (selectedTicket) {
        await api.resolveTicket(selectedTicket.ticket_id, approver.trim())
        setNotice(`Ticket #${selectedTicket.ticket_id} marked resolved.`)
        setReport(null)
      }
      closeApproval()
      await refresh()
    } catch (approvalError) {
      setError(approvalError instanceof Error ? approvalError.message : 'The action could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  const chooseTicket = (ticketId: number) => {
    setSelectedId(ticketId)
    setReport(null)
    setRunBaseline(null)
    setError('')
  }

  const agentSnapshots = useMemo(() => {
    return agentNames.map((name) => {
      let status: 'waiting' | 'working' | 'complete' | 'issue' = 'waiting'
      let summary = 'Waiting for a ticket-specific assignment.'
      let latestTool = ''
      let toolCount = 0
      for (const item of runEvents) {
        if (item.agent === name) {
          if (item.event === 'agent_started') { status = 'working'; summary = 'Reviewing the assigned work.' }
          if (item.event === 'agent_completed') {
            status = 'complete'
            summary = item.report?.summary ?? summary
          }
          if (item.event === 'agent_failed') { status = 'issue'; summary = item.error ?? 'This agent could not finish.' }
          if (item.event === 'mcp_tool_started') latestTool = `Checking ${titleCase(item.tool_name ?? 'database facts')}`
          if (item.event === 'mcp_tool_completed') { latestTool = `Checked ${titleCase(item.tool_name ?? 'database facts')}`; toolCount += 1 }
        }
        if (item.event === 'delegation_started' && item.to_agent === name) {
          status = 'working'
          summary = `Asked by ${item.from_agent ?? 'a teammate'} to investigate.`
        }
        if (item.event === 'delegation_completed' && item.to_agent === name) status = 'complete'
      }
      return { name, status, summary, latestTool, toolCount }
    })
  }, [runEvents])

  const activityEvents = [...runEvents].reverse().slice(0, 14)
  const canResolve = Boolean(selectedTicket && selectedTicket.status === 'open' && report && !running)

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />
      <header className="topbar">
        <a className="brand" href="#home" aria-label="Campus Customs workroom home">
          <span className="brand-mark"><Heart size={18} fill="currentColor" /></span>
          <span>Campus <b>Customs</b><small>AGENT WORKROOM</small></span>
        </a>
        <div className="topbar-right">
          <span className="connection"><span className={`connection-dot ${apiOnline ? '' : 'offline'}`} />{apiOnline ? 'Local API connected' : 'Backend unavailable'}</span>
          <button className="icon-button" onClick={() => void refresh()} aria-label="Refresh dashboard" title="Refresh dashboard"><RotateCw size={16} /></button>
        </div>
      </header>

      <main className="dashboard" id="home">
        <section className="welcome-row">
          <div>
            <p className="eyebrow"><Sparkles size={14} /> A little calm for a busy shop</p>
            <h1>The workroom<span className="period">.</span></h1>
            <p className="welcome-copy">See what needs care, follow the team’s thinking, and keep the final decisions human.</p>
          </div>
          <div className="today-note"><span className="note-flower">✿</span><span>One ticket at a time.<br /><b>Thoughtfully handled.</b></span></div>
        </section>

        {error && <div className="alert" role="alert"><CircleHelp size={17} /><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss"><X size={15} /></button></div>}
        {notice && <div className="notice" role="status"><CheckCircle2 size={17} /><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss"><X size={15} /></button></div>}

        <section className="overview" aria-label="Shop overview">
          <div className="overview-card open-card"><div className="overview-icon"><Inbox size={18} /></div><div><span>Open tickets</span><strong>{loading ? '—' : tickets.filter((ticket) => ticket.status === 'open').length.toString().padStart(2, '0')}</strong></div><span className="overview-caption">on today’s board</span></div>
          <div className="overview-card team-card"><div className="overview-icon"><Sparkles size={18} /></div><div><span>Agent team</span><strong>05</strong></div><span className="overview-caption">working with purpose</span></div>
          <div className="overview-card cash-card"><div className="overview-icon"><WalletCards size={18} /></div><div><span>Checking balance</span><strong>{cash ? money(cash.balance) : '—'}</strong></div><span className="overview-caption">as of {cash?.date ?? 'shop date'}</span></div>
        </section>

        <section className="work-grid">
          <aside className="ticket-rail panel">
            <div className="panel-heading"><div><span className="section-kicker">THE BOARD</span><h2>Tickets to tend</h2></div><span className="soft-count">{tickets.length}</span></div>
            <div className="ticket-list">
              {tickets.map((ticket) => (
                <button key={ticket.ticket_id} className={`ticket-card ${selectedId === ticket.ticket_id ? 'selected' : ''}`} onClick={() => chooseTicket(ticket.ticket_id)}>
                  <div className="ticket-card-top"><span className="ticket-number">#{ticket.ticket_id}</span><span className={`status-pill ${ticket.status === 'resolved' ? 'resolved' : ''}`}><i />{titleCase(ticket.status)}</span></div>
                  <h3>{ticket.subject}</h3>
                  <p>{ticket.requester}</p>
                  <div className="ticket-kind">{titleCase(ticket.type)}</div>
                  <ChevronRight className="ticket-arrow" size={16} />
                </button>
              ))}
              {!loading && tickets.length === 0 && <div className="empty-small">No tickets came back from the API.</div>}
              {loading && <div className="loading-line"><LoaderCircle size={15} className="spin" /> Gathering the board…</div>}
            </div>
            <div className="rail-footnote"><ShieldCheck size={15} /><span>The team can recommend. You stay in charge.</span></div>
          </aside>

          <section className="ticket-workspace panel" aria-live="polite">
            {selectedTicket ? <>
              <div className="workspace-head">
                <div>
                  <div className="breadcrumb"><span>BOARD</span><ChevronRight size={12} /><span>#{selectedTicket.ticket_id}</span></div>
                  <div className="title-line"><h2>{selectedTicket.subject}</h2><span className={`status-pill ${selectedTicket.status === 'resolved' ? 'resolved' : ''}`}><i />{titleCase(selectedTicket.status)}</span></div>
                  <p className="ticket-meta">{selectedTicket.requester} <span>·</span> {titleCase(selectedTicket.type)}</p>
                </div>
                <button className="run-button" onClick={() => void startRun()} disabled={running || selectedTicket.status !== 'open'}>
                  {running ? <><LoaderCircle size={16} className="spin" /> Team is working</> : <><Sparkles size={16} /> Start agent run</>}
                </button>
              </div>

              <div className="ticket-facts">
                <div className="fact-note"><span className="fact-label">THE REQUEST</span><p>{selectedTicket.notes || 'No additional ticket notes.'}</p></div>
                {selectedTicket.sku && <div className="fact-chip"><span>Item</span><b>{selectedTicket.sku}</b></div>}
                {selectedTicket.size && <div className="fact-chip"><span>Size</span><b>{selectedTicket.size}</b></div>}
                {selectedTicket.qty !== null && selectedTicket.qty !== undefined && <div className="fact-chip"><span>Quantity</span><b>{selectedTicket.qty}</b></div>}
                {selectedTicket.invoice_id && <div className="fact-chip"><span>Linked invoice</span><b>#{selectedTicket.invoice_id} · {money(selectedTicket.invoice_amount)}</b></div>}
                {selectedTicket.lease_next_due && <div className="fact-chip"><span>Rent due</span><b>{selectedTicket.lease_next_due}</b></div>}
              </div>

              <div className="section-divider"><span>YOUR TEAM</span><span className="divider-line" />{running && <span className="live-indicator"><i /> LIVE</span>}</div>
              <div className="agent-grid">
                {agentSnapshots.map((agent, index) => (
                  <article className={`agent-card agent-${agent.status}`} key={agent.name}>
                    <div className="agent-top"><span className={`agent-avatar avatar-${index}`}>{agent.name === 'Customer Service' ? <MessageCircle size={15} /> : agent.name === 'Accounting' ? <CreditCard size={15} /> : agent.name === 'Facilities' ? <Sparkles size={15} /> : agent.name === 'Inventory' ? <Inbox size={15} /> : <Heart size={15} />}</span><span className="agent-state">{agent.status === 'working' ? 'At work' : agent.status === 'complete' ? 'Done' : agent.status === 'issue' ? 'Needs attention' : 'On standby'}</span></div>
                    <h3>{agent.name}</h3>
                    <p>{agent.summary}</p>
                    {agent.latestTool && <span className="tool-chip"><Activity size={12} />{agent.latestTool}</span>}
                    {agent.toolCount > 0 && <span className="tool-count">{agent.toolCount} database {agent.toolCount === 1 ? 'check' : 'checks'}</span>}
                  </article>
                ))}
              </div>

              <div className="section-divider activity-divider"><span>RUN NOTES</span><span className="divider-line" />{activityEvents.length > 0 && <span className="note-count">{activityEvents.length} updates</span>}</div>
              {activityEvents.length ? <div className="activity-feed">
                {activityEvents.map((event) => (
                  <article className={`activity-item ${event.event.includes('failed') ? 'activity-error' : ''}`} key={`${event.run_id}-${event.sequence}`}>
                    <div className="activity-icon">{eventIcon(event)}</div>
                    <div className="activity-copy"><div className="activity-title">{eventHeadline(event)}</div>
                      {event.event === 'mcp_tool_completed' && event.tool_output !== undefined && <details className="evidence"><summary>View database result</summary><pre>{compact(event.tool_output)}</pre></details>}
                      {event.event === 'agent_completed' && event.report?.verified_facts?.length ? <p className="fact-proof">Verified: {event.report.verified_facts.slice(0, 2).join(' · ')}</p> : null}
                    </div>
                    <time>{shortTime(event.timestamp_utc)}</time>
                  </article>
                ))}
              </div> : <div className="activity-empty"><div className="empty-orbit"><Sparkles size={19} /></div><strong>{running ? 'The team is getting settled…' : 'A quiet board, for now.'}</strong><span>{running ? 'Agent notes and verified tool checks will appear here as they happen.' : 'Choose an open ticket and start a run to follow the team’s work.'}</span></div>}

              {report && <div className="recommendation-card"><div className="recommendation-mark"><BadgeCheck size={18} /></div><div><span className="section-kicker">BOSS SUMMARY</span><h3>{report.summary}</h3>{report.recommendations.length > 0 && <ul>{report.recommendations.slice(0, 3).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}{report.unknowns.length > 0 && <p className="unknowns"><CircleHelp size={14} /> Still unknown: {report.unknowns.join(' · ')}</p>}</div></div>}

              {approvalRequired && <section className="approval-callout"><div className="approval-icon"><LockKeyhole size={17} /></div><div className="approval-copy"><span className="section-kicker">YOUR REVIEW NEEDED</span><h3>The team flagged a decision for you.</h3><p>Review the recommendation above, then choose what to approve. Agents never submit payments.</p></div><div className="approval-actions">{selectedTicket.invoice_id && <button className="soft-action" onClick={() => setApprovalKind('payment')}><Banknote size={15} /> Review invoice payment</button>}<button className="soft-action" onClick={() => setApprovalKind('purchase')}><WalletCards size={15} /> Review purchase outflow</button></div></section>}

              <div className="workspace-footer">
                {canResolve ? <div className="resolve-prompt"><span><CheckCircle2 size={16} /> Run complete — review the findings before changing status.</span><button className="resolve-button" onClick={() => setApprovalKind('resolve')}><Check size={15} /> Mark resolved</button></div>
                  : <span className="safety-note"><ShieldCheck size={15} /> Finishing a run does not automatically resolve a ticket.</span>}
                <span className="footer-hint"><Clock3 size={13} /> Activity refreshes automatically</span>
              </div>
            </> : <div className="workspace-blank"><LoaderCircle size={20} className="spin" /> Loading the board…</div>}
          </section>
        </section>

        <footer className="bottom-note"><span><ShieldCheck size={14} /> Human decisions stay human.</span><span>Campus Customs <i>·</i> Local operations board</span></footer>
      </main>

      {approvalKind && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) closeApproval() }}>
        <section className="approval-modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <button className="modal-close" onClick={closeApproval} disabled={busy} aria-label="Close dialog"><X size={17} /></button>
          <div className="modal-icon">{approvalKind === 'payment' ? <Banknote size={20} /> : approvalKind === 'purchase' ? <WalletCards size={20} /> : <CheckCircle2 size={20} />}</div>
          <span className="section-kicker">HUMAN ACTION</span>
          <h2 id="modal-title">{approvalKind === 'payment' ? 'Approve invoice payment?' : approvalKind === 'purchase' ? 'Approve purchase outflow?' : `Resolve ticket #${selectedTicket?.ticket_id}?`}</h2>
          <p className="modal-copy">{approvalKind === 'payment'
            ? `This records invoice #${selectedTicket?.invoice_id ?? '—'} (${money(selectedTicket?.invoice_amount)}) against checking. The server will refuse if cash is insufficient.`
            : approvalKind === 'purchase'
              ? 'This records a cash outflow only. It does not create an order or contact a vendor.'
              : 'You reviewed the team’s findings. This changes the ticket status in the working database.'}</p>
          <form onSubmit={(event) => void submitApproval(event)}>
            {approvalKind === 'purchase' && <label className="form-field">Purchase amount (USD)<input autoFocus type="number" min="0.01" step="0.01" value={purchaseAmount} onChange={(event) => setPurchaseAmount(event.target.value)} placeholder="0.00" required /></label>}
            <label className="form-field">Your name<input autoFocus={approvalKind !== 'purchase'} value={approver} onChange={(event) => setApprover(event.target.value)} placeholder="Name for the audit record" required /></label>
            <label className="form-field">Type <b>{approvalKind === 'payment' ? 'APPROVE PAYMENT' : approvalKind === 'purchase' ? 'APPROVE PURCHASE' : 'RESOLVE TICKET'}</b> to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="Type the confirmation phrase" required /></label>
            <button className="confirm-button" type="submit" disabled={busy || !approver.trim() || confirmation.trim() !== (approvalKind === 'payment' ? 'APPROVE PAYMENT' : approvalKind === 'purchase' ? 'APPROVE PURCHASE' : 'RESOLVE TICKET')}>
              {busy ? <><LoaderCircle size={16} className="spin" /> Saving…</> : approvalKind === 'resolve' ? <><Check size={16} /> Confirm resolution</> : <><LockKeyhole size={15} /> Confirm {approvalKind === 'payment' ? 'payment' : 'purchase'}</>}
            </button>
          </form>
          <p className="modal-safety"><LockKeyhole size={13} /> This local homework app records your name for the audit trail; it is not account authentication.</p>
        </section>
      </div>}
    </div>
  )
}

export default App
