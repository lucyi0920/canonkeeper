"""Data contracts shared by the API, the agents and the store.

Models used as Gemini structured-output schemas keep to plain types
(str / int / bool / float / lists of models) so the JSON schema stays portable.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Canon ----------

class Trait(BaseModel):
    name: str = Field(description="e.g. scar, hair, eyes, outfit, weapon, signature item")
    value: str = Field(description="precise description; for location-dependent traits state the side in the VIEWER'S perspective")
    side: str = Field(default="none", description="viewer_left | viewer_right | none — side of the image canvas, only for location-dependent traits")
    since_episode: int = Field(default=0, description="episode where the trait was established, 0 if from the start")


class Character(BaseModel):
    name: str
    aliases: list[str] = []
    role: str = ""
    status: str = Field(description="alive | dead | unknown")
    status_since_episode: int = 0
    status_detail: str = ""
    traits: list[Trait] = []
    reference_labels: list[str] = Field(default=[], description="labels of reference images that show this character")


class Event(BaseModel):
    episode: int
    kind: str = Field(description="death | injury | reveal | setup | payoff | item | relationship | progression")
    description: str


class Thread(BaseModel):
    id: str
    setup_episode: int
    description: str
    resolved: bool
    resolved_episode: int = 0


class Evidence(BaseModel):
    fact_id: str
    fact: str
    episode: int
    quote: str = Field(description="verbatim excerpt from the corpus that supports the fact")
    verified: bool = False


class CanonBible(BaseModel):
    series_title: str
    characters: list[Character]
    events: list[Event]
    threads: list[Thread]
    evidence: list[Evidence]


class ReferenceImage(BaseModel):
    label: str               # e.g. "EP3 panel 2"
    character: str = ""
    episode: int = 0
    asset: str               # asset ref: "seed:<file>" or "asset:<id>"


class EpisodeMeta(BaseModel):
    episode: int
    title: str = ""
    chars: int = 0
    images: int = 0


class CanonContext(BaseModel):
    interaction_id: str = ""
    model: str = ""
    input_tokens: int = 0
    token_source: str = "measured"
    created_at: float = 0
    mode: str = "single"      # single | volumes


class CanonVerification(BaseModel):
    total: int = 0
    verified: int = 0
    repaired: int = 0


class Canon(BaseModel):
    canon_id: str
    series_title: str
    bible: CanonBible
    episodes: list[EpisodeMeta]
    references: list[ReferenceImage]
    corpus_asset: str = ""    # asset ref of the stored corpus JSON (needed to refresh the context)
    context: CanonContext = CanonContext()
    verification: CanonVerification = CanonVerification()
    build_seconds: float = 0
    built_at: float = 0


# ---------- Draft ----------

class Panel(BaseModel):
    id: str
    index: int
    image: str = ""           # asset ref; empty if no art yet
    caption: str = ""
    dialogue: str = ""

    @property
    def ref(self) -> str:
        return f"draft panel {self.index}"


class Draft(BaseModel):
    episode: int
    title: str = ""
    panels: list[Panel]


# ---------- Planning ----------

class CharacterSighting(BaseModel):
    name: str = Field(description="canon character name, or 'Unknown'")
    confidence: float = Field(description="0..1")
    cues: str = Field(description="visual and textual cues that identify the character")


class PanelReading(BaseModel):
    panel_id: str
    characters_present: list[CharacterSighting]
    scene: str


class CanonBrief(BaseModel):
    fact: str
    episode: int
    quote: str


class PlannedCheck(BaseModel):
    check_id: str
    agent: str = Field(description="name of a registered verification agent")
    panel_ids: list[str]
    character: str = ""
    reference_label: str = Field(default="", description="reference image label to compare against (appearance checks)")
    focus: str = Field(description="what exactly the agent must verify")
    canon_brief: list[CanonBrief] = Field(description="the canon facts the agent needs, with episode and verbatim quote")
    reason: str


class CheckPlan(BaseModel):
    panels: list[PanelReading]
    checks: list[PlannedCheck]


# ---------- Findings ----------

class Mismatch(BaseModel):
    trait: str
    canon: str
    draft: str


class AgentFinding(BaseModel):
    """What a verification agent returns (structured output)."""
    panel_id: str
    severity: str = Field(description="critical | warning")
    title: str = Field(description="short headline, max 8 words")
    explanation: str = Field(description="cite both the draft and the canon fact")
    canon_ref: str = Field(description="e.g. 'EP7 panel 4' or 'EP7'")
    suggested_fix: str
    mismatches: list[Mismatch] = []


class Adjudication(BaseModel):
    verdict: str              # confirm | reject | needs_human
    severity: str
    evidence_episode: int = 0
    evidence_quote: str = ""
    rationale: str = ""


class Decision(BaseModel):
    action: str               # dismiss | keep | send_back
    note: str = ""
    at: float = 0


class Finding(BaseModel):
    id: str
    check_id: str
    agent: str
    dimension: str
    severity: str
    panel_id: str
    panel_ref: str
    character: str = ""
    reference_label: str = ""
    canon_ref: str
    title: str
    explanation: str
    suggested_fix: str
    mismatches: list[Mismatch] = []
    can_regenerate: bool = False
    adjudication: Optional[Adjudication] = None
    status: Literal["open", "resolved", "dismissed", "rejected"] = "open"
    needs_human: bool = False
    regenerated_image: str = ""
    regen_attempts: int = 0
    resolution_note: str = ""
    decision: Optional[Decision] = None


class Report(BaseModel):
    run_id: str
    findings: list[Finding]
    plan: Optional[CheckPlan] = None
    score: int
    checks_total: int
    checks_passed: int
    checks_failed: int
    shippable: bool
    verified_at: float
    models: dict[str, str]


# ---------- Runs / trace ----------

class TraceStep(BaseModel):
    t_ms: int
    actor: str
    model: str = ""
    action: str
    detail: str = ""
    status: Literal["ok", "error", "info", "running"] = "ok"
    duration_ms: int = 0
    tokens: int = 0


# ---------- Session ----------

class Session(BaseModel):
    session_id: str
    canon_id: str
    draft: Draft
    report: Optional[Report] = None
    memo: str = ""
    shipped_at: float = 0
    created_at: float = 0
    is_demo: bool = False
