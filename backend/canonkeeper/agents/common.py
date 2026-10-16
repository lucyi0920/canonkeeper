from __future__ import annotations

import hashlib

from pydantic import BaseModel

from .. import llm
from ..schemas import AgentFinding, CanonBrief, Draft, Finding, Panel, PlannedCheck


class AgentFindingList(BaseModel):
    findings: list[AgentFinding]


def brief_text(brief: list[CanonBrief]) -> str:
    if not brief:
        return "(none provided)"
    return "\n".join(f'- {b.fact} [EP{b.episode}] "{b.quote}"' for b in brief)


def panels_for(draft: Draft, ids: list[str]) -> list[Panel]:
    wanted = set(ids)
    return [p for p in draft.panels if p.id in wanted] or list(draft.panels)


def panel_parts(panels: list[Panel]) -> list[dict]:
    parts: list[dict] = []
    for p in panels:
        parts.append(llm.text_part(
            f"--- PANEL panel_id={p.id} ({p.ref}) ---\nCaption: {p.caption or '(none)'}\nDialogue: {p.dialogue or '(none)'}"))
        if p.image:
            parts.append(llm.image_part(p.image))
    return parts


def clean_title(title: str, limit: int = 70) -> str:
    """Keeps a model-written headline short: first clause, word-bounded."""
    t = " ".join((title or "").split())
    for sep in (" (", ". ", " — ", " - ", ": "):
        if sep in t[8:]:
            t = t[: t.index(sep, 8)]
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t.strip(" .,;") or "Continuity issue"


def finding_id(check_id: str, panel_id: str, title: str) -> str:
    return "f-" + hashlib.sha1(f"{check_id}|{panel_id}|{title}".encode()).hexdigest()[:8]


def to_findings(raw: list[AgentFinding], check: PlannedCheck, draft: Draft, *, agent: str,
                dimension: str, can_regenerate: bool) -> list[Finding]:
    by_id = {p.id: p for p in draft.panels}
    out = []
    for f in raw:
        panel = by_id.get(f.panel_id)
        if panel is None and check.panel_ids:
            panel = by_id.get(check.panel_ids[0])
        if panel is None:
            continue
        sev = f.severity if f.severity in ("critical", "warning") else "critical"
        out.append(Finding(
            id=finding_id(check.check_id, panel.id, f.title), check_id=check.check_id, agent=agent,
            dimension=dimension, severity=sev, panel_id=panel.id, panel_ref=panel.ref,
            character=check.character, reference_label=check.reference_label, canon_ref=f.canon_ref,
            title=clean_title(f.title), explanation=f.explanation, suggested_fix=f.suggested_fix,
            mismatches=f.mismatches, can_regenerate=can_regenerate,
        ))
    return out
