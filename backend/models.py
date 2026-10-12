"""Shared typed data contracts for the Campus Customs agent team."""

from __future__ import annotations

from dataclasses import dataclass, field
from mcp import ClientSession
from pydantic import BaseModel, Field

from .audit import AuditTrail


class AgentReport(BaseModel):
    """Structured result returned by every specialist and the Boss."""

    agent: str = Field(description="Name of the agent producing this report")
    summary: str = Field(description="Short answer or recommendation")
    verified_facts: list[str] = Field(
        default_factory=list,
        description="Facts directly supported by MCP data or delegated reports",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Proposed next steps; these are not executed actions",
    )
    customer_message_draft: str | None = Field(
        default=None,
        description="Optional unsent draft for the customer; never send it",
    )
    requires_human_approval: bool = Field(
        default=False,
        description="True when a proposed payment or other approval is needed",
    )
    unknowns: list[str] = Field(
        default_factory=list,
        description="Important information that could not be verified",
    )


@dataclass
class TeamRuntime:
    """Per-run MCP session and bounded delegation-chain state."""

    mcp: ClientSession
    active_agents: list[str] = field(default_factory=list)
    max_delegation_depth: int = 6
    audit: AuditTrail = field(default_factory=AuditTrail)
