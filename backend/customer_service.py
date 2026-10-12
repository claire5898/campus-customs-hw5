"""Customer Service agent factory."""

from pydantic_ai import Agent
from pydantic_ai.models import Model

from .agent_factory import create_role_agent
from .models import AgentReport, TeamRuntime


def create_agent(model: Model | str | None = None) -> Agent[TeamRuntime, AgentReport]:
    return create_role_agent("Customer Service", model)
