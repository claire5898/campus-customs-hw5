"""Build and run the fully connected Campus Customs PydanticAI team."""

from __future__ import annotations

import asyncio
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.models import Model

from . import accounting, boss, customer_service, facilities, inventory
from .config import make_model
from .mcp_tools import WORKING_DATABASE, open_mcp_session
from .models import AgentReport, TeamRuntime


AGENT_CREATORS = {
    "Boss": boss.create_agent,
    "Inventory": inventory.create_agent,
    "Accounting": accounting.create_agent,
    "Facilities": facilities.create_agent,
    "Customer Service": customer_service.create_agent,
}
AGENT_NAMES = tuple(AGENT_CREATORS)
MAX_DELEGATION_DEPTH = 6
MAX_MODEL_REQUESTS = 40
MAX_TOOL_CALLS = 32
MAX_TOTAL_TOKENS = 50_000


def build_agent_team(
    model: Model | str | None = None,
) -> dict[str, Agent[TeamRuntime, AgentReport]]:
    """Create the five role agents, all using gpt-6-luna through Portkey by default."""
    shared_model = model or make_model()
    agents = {
        role: creator(shared_model)
        for role, creator in AGENT_CREATORS.items()
    }

    # Full directed peer network: each agent can delegate to each of the other four.
    for source_name, source_agent in agents.items():
        for target_name, target_agent in agents.items():
            if source_name == target_name:
                continue

            def make_delegate(
                source: str, target: str, delegated_agent: Agent[TeamRuntime, AgentReport]
            ):
                async def delegate(
                    ctx: RunContext[TeamRuntime], task: str
                ) -> AgentReport:
                    """Delegate a focused investigation to a peer, then return its report."""
                    runtime = ctx.deps
                    current_source = runtime.active_agents[-1] if runtime.active_agents else source
                    delegation = {
                        "from_agent": current_source,
                        "to_agent": target,
                        "agent_chain": list(runtime.active_agents),
                        "task": task,
                    }
                    if target in runtime.active_agents:
                        runtime.audit.append("delegation_blocked_cycle", **delegation)
                        return AgentReport(
                            agent=target,
                            summary=f"Delegation skipped to prevent a cycle: {target} is already active.",
                            unknowns=["A peer in this delegation chain is already active."],
                        )
                    if len(runtime.active_agents) >= runtime.max_delegation_depth:
                        runtime.audit.append("delegation_blocked_depth", **delegation)
                        return AgentReport(
                            agent=target,
                            summary="Delegation depth limit reached; summarize available findings.",
                            unknowns=["No deeper delegation was attempted."],
                        )
                    runtime.active_agents.append(target)
                    runtime.audit.append("delegation_started", **delegation)
                    runtime.audit.append(
                        "agent_started", agent=target, agent_chain=list(runtime.active_agents),
                        task=task,
                    )
                    try:
                        result = await delegated_agent.run(
                            task,
                            deps=runtime,
                            usage=ctx.usage,
                        )
                        runtime.audit.append(
                            "agent_completed", agent=target,
                            agent_chain=list(runtime.active_agents), report=result.output,
                        )
                        runtime.audit.append(
                            "delegation_completed", **delegation, report=result.output,
                        )
                        return result.output
                    except Exception as error:
                        runtime.audit.append(
                            "agent_failed", agent=target,
                            agent_chain=list(runtime.active_agents),
                            error_type=type(error).__name__, error=str(error),
                        )
                        runtime.audit.append(
                            "delegation_failed", **delegation,
                            error_type=type(error).__name__, error=str(error),
                        )
                        raise
                    finally:
                        runtime.active_agents.pop()

                delegate.__name__ = f"delegate_to_{target.lower().replace(' ', '_')}"
                delegate.__doc__ = f"Ask {target} to investigate a focused task and return a typed report."
                return delegate

            source_agent.tool(make_delegate(source_name, target_name, target_agent))
    return agents


async def run_boss(
    task: str,
    *,
    model: Model | str | None = None,
) -> AgentReport:
    """Run Boss with one live MCP session and bounded peer delegation."""
    team = build_agent_team(model)
    async with open_mcp_session() as session:
        runtime = TeamRuntime(
            mcp=session,
            active_agents=["Boss"],
            max_delegation_depth=MAX_DELEGATION_DEPTH,
        )
        runtime.audit.append(
            "run_started", agent="Boss", agent_chain=["Boss"], task=task,
            database=str(WORKING_DATABASE),
        )
        runtime.audit.append("agent_started", agent="Boss", agent_chain=["Boss"], task=task)
        try:
            result = await team["Boss"].run(
                task,
                deps=runtime,
                usage_limits=UsageLimits(
                    request_limit=MAX_MODEL_REQUESTS,
                    tool_calls_limit=MAX_TOOL_CALLS,
                    total_tokens_limit=MAX_TOTAL_TOKENS,
                ),
            )
            runtime.audit.append(
                "agent_completed", agent="Boss", agent_chain=["Boss"], report=result.output,
            )
            runtime.audit.append("run_completed", agent="Boss", report=result.output)
            return result.output
        except Exception as error:
            runtime.audit.append(
                "agent_failed", agent="Boss", agent_chain=["Boss"],
                error_type=type(error).__name__, error=str(error),
            )
            runtime.audit.append(
                "run_failed", agent="Boss", error_type=type(error).__name__, error=str(error),
            )
            raise


def run_boss_sync(
    task: str,
    *,
    model: Model | str | None = None,
) -> AgentReport:
    """Synchronous entry point for scripts and later FastAPI integration."""
    return asyncio.run(run_boss(task, model=model))
