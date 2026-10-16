"""Foreshadowing agent — setup/payoff threads."""
from __future__ import annotations

from .. import config, llm, prompts
from ..schemas import Finding, PlannedCheck
from . import Agent, AgentContext, register
from .common import AgentFindingList, brief_text, panel_parts, panels_for, to_findings


async def run(check: PlannedCheck, ctx: AgentContext) -> list[Finding]:
    panels = panels_for(ctx.draft, check.panel_ids)
    prompt = prompts.FORESHADOW.format(brief=brief_text(check.canon_brief), focus=check.focus)
    res = await llm.generate(config.MODEL_SUBAGENT, [llm.text_part(prompt), *panel_parts(panels)],
                             schema=AgentFindingList, thinking="low", max_output_tokens=2500, timeout=75)
    return to_findings(res.parsed.findings, check, ctx.draft, agent="foreshadowing",
                       dimension="foreshadowing", can_regenerate=False)


register(Agent(
    name="foreshadowing", dimension="foreshadowing", model=config.MODEL_SUBAGENT, can_regenerate=False,
    description=("Checks setup/payoff threads: resolved threads treated as open, payoffs that contradict their setup, "
                 "new rules or items that break an established thread rule. Needs: panel_ids, canon_brief with the relevant threads."),
    run=run,
))
