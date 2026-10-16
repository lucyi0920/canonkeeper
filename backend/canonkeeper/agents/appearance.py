"""Appearance agent — multimodal comparison of a draft panel against a canon reference image."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .. import config, llm, prompts
from ..schemas import Finding, Mismatch, PlannedCheck
from . import Agent, AgentContext, register
from .common import brief_text, clean_title, finding_id


class Observation(BaseModel):
    trait: str = Field(json_schema_extra={"maxLength": 60})
    canon_image: str = Field(json_schema_extra={"maxLength": 200})
    draft_image: str = Field(json_schema_extra={"maxLength": 200})


class AppearanceVerdict(BaseModel):
    character_visible: bool
    consistent: bool
    observations: list[Observation]
    mismatches: list[Mismatch]
    severity: str = "critical"
    title: str = Field(default="", description="max 8 words", json_schema_extra={"maxLength": 90})
    explanation: str = Field(default="", json_schema_extra={"maxLength": 700})
    suggested_fix: str = Field(default="", json_schema_extra={"maxLength": 400})


def reference_asset(canon, label: str) -> str:
    for r in canon.references:
        if r.label.lower() == label.lower():
            return r.asset
    return ""


async def check_image(check: PlannedCheck, canon, image_ref: str, panel_ref: str) -> AppearanceVerdict:
    """Compares one draft image with the check's reference image. Used for verification and re-verification."""
    ref_asset = reference_asset(canon, check.reference_label)
    if not ref_asset:
        raise ValueError(f"reference '{check.reference_label}' not found in canon")
    prompt = prompts.APPEARANCE.format(
        character=check.character or "the character", focus=check.focus,
        brief=brief_text(check.canon_brief), reference_label=check.reference_label, panel_ref=panel_ref)
    res = await llm.generate(
        config.MODEL_SUBAGENT,
        [llm.text_part(prompt), llm.image_part(ref_asset), llm.image_part(image_ref)],
        schema=AppearanceVerdict, thinking="medium", max_output_tokens=6000, timeout=60)
    return res.parsed


async def run(check: PlannedCheck, ctx: AgentContext) -> list[Finding]:
    panel = next((p for p in ctx.draft.panels if p.id in check.panel_ids and p.image), None)
    if panel is None:
        return []
    v = await check_image(check, ctx.canon, panel.image, panel.ref)
    if v.consistent or not v.character_visible:
        return []
    return [Finding(
        id=finding_id(check.check_id, panel.id, v.title or "appearance"), check_id=check.check_id,
        agent="appearance", dimension="appearance",
        severity=v.severity if v.severity in ("critical", "warning") else "critical",
        panel_id=panel.id, panel_ref=panel.ref, character=check.character,
        reference_label=check.reference_label, canon_ref=check.reference_label,
        title=clean_title(v.title) if v.title else f"{check.character} differs from {check.reference_label}",
        explanation=v.explanation, suggested_fix=v.suggested_fix, mismatches=v.mismatches,
        can_regenerate=True,
    )]


register(Agent(
    name="appearance", dimension="appearance", model=config.MODEL_SUBAGENT, can_regenerate=True,
    description=("Multimodal. Compares ONE draft panel with ONE canon reference image of ONE character and flags "
                 "contradictions of durable visual identity (scars and which side, marks, hair, eyes, outfit, signature items). "
                 "Needs: panel_ids=[one panel], character, reference_label, canon_brief with the character's traits."),
    run=run,
))
