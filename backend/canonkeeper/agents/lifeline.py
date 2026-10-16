"""Lifeline agent — life status, items and timeline, reading both art and text."""
from __future__ import annotations

from .. import config, llm, prompts
from ..schemas import Finding, PlannedCheck
from . import Agent, AgentContext, register
from .common import AgentFindingList, brief_text, panel_parts, panels_for, to_findings


def sightings_text(ctx: AgentContext, ids: list[str]) -> str:
    rows = []
    for pr in ctx.plan.panels:
        if not ids or pr.panel_id in ids:
            who = ", ".join(f"{s.name} ({s.confidence:.2f})" for s in pr.characters_present) or "nobody identified"
            rows.append(f"{pr.panel_id}: {who}")
    return "; ".join(rows) or "(none)"


async def run(check: PlannedCheck, ctx: AgentContext) -> list[Finding]:
    panels = panels_for(ctx.draft, check.panel_ids)
    prompt = prompts.LIFELINE.format(brief=brief_text(check.canon_brief),
                                     sightings=sightings_text(ctx, check.panel_ids), focus=check.focus)
    res = await llm.generate(config.MODEL_SUBAGENT, [llm.text_part(prompt), *panel_parts(panels)],
                             schema=AgentFindingList, thinking="low", max_output_tokens=6000, timeout=60)
    return to_findings(res.parsed.findings, check, ctx.draft, agent="lifeline",
                       dimension="lifeline", can_regenerate=False)


register(Agent(
    name="lifeline", dimension="lifeline", model=config.MODEL_SUBAGENT, can_regenerate=False,
    description=("Multimodal. Reads panel art AND text to catch life-status, item and timeline contradictions "
                 "(dead characters present or acting alive, destroyed items back intact, events retold differently). "
                 "Respects explicit flashback/vision framing. Needs: panel_ids (one or more), canon_brief with statuses, deaths, items and events."),
    run=run,
))
