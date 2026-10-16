"""Verification agent registry.

Each agent declares what it verifies; the Argon planner reads these descriptions
and decides which agent runs on which panels. Adding a new kind of check means
registering one more agent — the planner picks it up without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from ..schemas import CheckPlan, Draft, Finding, PlannedCheck


@dataclass
class AgentContext:
    canon: "object"          # schemas.Canon
    draft: Draft
    plan: CheckPlan


@dataclass
class Agent:
    name: str
    dimension: str
    model: str
    description: str
    can_regenerate: bool
    run: Callable[[PlannedCheck, AgentContext], Awaitable[list[Finding]]]


REGISTRY: dict[str, Agent] = {}


def register(agent: Agent) -> None:
    REGISTRY[agent.name] = agent


def describe() -> str:
    return "\n".join(f"- {a.name} ({a.model}): {a.description}" for a in REGISTRY.values())


def load_all() -> None:
    from . import appearance, foreshadow, lifeline  # noqa: F401  (registration side effects)
