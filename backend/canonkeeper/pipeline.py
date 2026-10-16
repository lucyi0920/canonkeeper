"""Verification pipeline: Argon plans → Flash agents verify in parallel → Argon adjudicates → score.
Plus the closed regeneration loop, editor decisions, the editor memo and draft parsing."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional

from pydantic import BaseModel

from . import agents, canon as canon_mod, config, llm, prompts, scoring, store
from .agents import AgentContext
from .agents.appearance import check_image, reference_asset
from .schemas import (Adjudication, CheckPlan, Decision, Draft, Finding, Panel, PlannedCheck, Report,
                      Session)
from .trace import Tracer

agents.load_all()

MODELS = {"orchestrator": config.MODEL_ORCHESTRATOR, "subagent": config.MODEL_SUBAGENT, "image": config.MODEL_IMAGE}


# ---------- sessions ----------

def demo_draft() -> Draft:
    src = json.loads((config.SEED_DIR / "source_draft.json").read_text(encoding="utf-8"))
    panels = [Panel(id=f"p{p['panel']}", index=p["panel"], image="seed:" + p["image_path"].rsplit("/", 1)[-1],
                    caption=p["caption"], dialogue=p["dialogue"]) for p in src["panels"]]
    title = src["title"].split("—", 1)[-1].strip()
    return Draft(episode=src["episode"], title=title, panels=panels)


def create_session(canon_id: str, draft: Optional[Draft] = None) -> Session:
    canon_mod.load(canon_id)  # validates the canon exists (installs the demo on first use)
    is_demo = canon_id == config.DEMO_CANON_ID and draft is None
    if draft is None:
        draft = demo_draft() if canon_id == config.DEMO_CANON_ID else Draft(episode=1, title="", panels=[])
    s = Session(session_id=uuid.uuid4().hex, canon_id=canon_id, draft=draft, created_at=time.time(), is_demo=is_demo)
    save_session(s)
    return s


def load_session(session_id: str) -> Session:
    doc = store.docs().get("sessions", session_id)
    if doc is None:
        raise KeyError(f"session '{session_id}' not found")
    return Session.model_validate(doc)


def save_session(s: Session) -> None:
    store.docs().set("sessions", s.session_id, s.model_dump())


def update_draft(session_id: str, draft: Draft) -> Session:
    s = load_session(session_id)
    s.draft = draft
    s.report = None
    s.memo = ""
    s.shipped_at = 0
    s.is_demo = False
    save_session(s)
    return s


# ---------- verify ----------

class Verdict(BaseModel):
    finding_id: str
    verdict: str
    severity: str
    evidence_episode: int = 0
    evidence_quote: str = ""
    rationale: str = ""


class AdjudicationList(BaseModel):
    verdicts: list[Verdict]


def _draft_parts(draft: Draft) -> list[dict]:
    parts = []
    for p in draft.panels:
        parts.append(llm.text_part(f"--- PANEL panel_id={p.id} ({p.ref}) ---\nCaption: {p.caption or '(none)'}\nDialogue: {p.dialogue or '(none)'}"))
        if p.image:
            parts.append(llm.image_part(p.image))
        else:
            parts.append(llm.text_part("(no art attached for this panel)"))
    return parts


async def plan_checks(canon, draft: Draft, tracer: Tracer) -> CheckPlan:
    refs = ", ".join(f"{r.label} → {r.character or '?'}" for r in canon.references) or "(none)"
    prompt = prompts.PLANNER.format(episode=draft.episode, title=draft.title, agents=agents.describe(), references=refs)
    async with tracer.span("Argon · planner", "Reading every panel and planning checks",
                           model=config.MODEL_ORCHESTRATOR) as s:
        res = await canon_mod.chained(canon, config.MODEL_ORCHESTRATOR, [llm.text_part(prompt), *_draft_parts(draft)],
                                      tracer, schema=CheckPlan, thinking="low")
        plan: CheckPlan = res.parsed
        plan.checks = [c for c in plan.checks if c.agent in agents.REGISTRY]
        seen = "; ".join(f"{pr.panel_id}: " + (", ".join(c.name for c in pr.characters_present) or "—") for pr in plan.panels)
        s["detail"] = f"{len(plan.checks)} checks planned · seen in art: {seen}"
        s["tokens"] = res.input_tokens
    for c in plan.checks:
        tracer.log("Argon · planner", f"Plan: {c.agent} → {', '.join(c.panel_ids)}", c.reason, model=config.MODEL_ORCHESTRATOR)
    return plan


async def run_checks(canon, draft: Draft, plan: CheckPlan, tracer: Tracer) -> tuple[list[Finding], int]:
    ctx = AgentContext(canon=canon, draft=draft, plan=plan)
    sem = asyncio.Semaphore(config.SUBAGENT_CONCURRENCY)
    failed = 0

    async def one(check: PlannedCheck) -> list[Finding]:
        nonlocal failed
        agent = agents.REGISTRY[check.agent]
        label = f"{check.character + ' · ' if check.character else ''}{', '.join(check.panel_ids)}"
        async with sem:
            try:
                async with tracer.span(f"Flash · {agent.name}", f"Checking {label}", model=agent.model, detail=check.focus) as s:
                    found = await agent.run(check, ctx)
                    s["detail"] = ("; ".join(f.title for f in found)) if found else "consistent with canon"
                    s["status"] = "error" if found else "ok"
                    return found
            except Exception as exc:
                failed += 1
                # fail toward human review: an unverified check blocks shipping until the editor looks
                p = next((p for p in draft.panels if p.id in check.panel_ids), draft.panels[0])
                return [Finding(id=f"f-err-{check.check_id}", check_id=check.check_id, agent=agent.name,
                                dimension=agent.dimension, severity="critical", panel_id=p.id, panel_ref=p.ref,
                                character=check.character, canon_ref="—", title="Check could not run",
                                explanation=f"The {agent.name} agent failed ({type(exc).__name__}). This panel is unverified.",
                                suggested_fix="Re-run verification, or review this panel manually.", needs_human=True)]

    results = await asyncio.gather(*(one(c) for c in plan.checks))
    return [f for batch in results for f in batch], failed


async def adjudicate(canon, draft: Draft, findings: list[Finding], tracer: Tracer) -> None:
    real = [f for f in findings if not f.id.startswith("f-err-")]
    if not real:
        return
    listing = "\n".join(
        f"- finding_id={f.id} | {f.dimension} | {f.panel_ref} | {f.title}: {f.explanation} (canon_ref {f.canon_ref})" for f in real)
    flagged = [p for p in draft.panels if p.id in {f.panel_id for f in real}]
    try:
        async with tracer.span("Argon · adjudicator", f"Cross-examining {len(real)} findings against the full series",
                               model=config.MODEL_ORCHESTRATOR) as s:
            res = await canon_mod.chained(canon, config.MODEL_ORCHESTRATOR,
                                          [llm.text_part(prompts.ADJUDICATOR.format(episode=draft.episode, findings=listing)),
                                           *_draft_parts(Draft(episode=draft.episode, title=draft.title, panels=flagged))],
                                          tracer, schema=AdjudicationList, thinking="low")
            verdicts = {v.finding_id: v for v in res.parsed.verdicts}
            counts = {"confirm": 0, "reject": 0, "needs_human": 0}
            for f in real:
                v = verdicts.get(f.id)
                if v is None:
                    f.needs_human = True
                    continue
                verdict = v.verdict if v.verdict in counts else "needs_human"
                counts[verdict] += 1
                f.adjudication = Adjudication(verdict=verdict, severity=v.severity, evidence_episode=v.evidence_episode,
                                              evidence_quote=v.evidence_quote, rationale=v.rationale)
                if v.severity in ("critical", "warning"):
                    f.severity = v.severity
                if verdict == "reject":
                    f.status = "rejected"
                elif verdict == "needs_human":
                    f.needs_human = True
            s["detail"] = f"{counts['confirm']} confirmed · {counts['needs_human']} for the editor · {counts['reject']} overruled"
            s["tokens"] = res.input_tokens
    except Exception:
        for f in real:  # keep every flag for human review
            f.needs_human = True


async def verify(session_id: str, run_id: str) -> Report:
    tracer = Tracer(run_id, "verify")
    try:
        s = load_session(session_id)
        if not s.draft.panels:
            raise ValueError("The draft has no panels yet.")
        canon = canon_mod.load(s.canon_id)
        plan = await plan_checks(canon, s.draft, tracer)
        findings, failed = await run_checks(canon, s.draft, plan, tracer)
        await adjudicate(canon, s.draft, findings, tracer)
        report = scoring.recompute(Report(
            run_id=run_id, findings=findings, plan=plan, score=0, checks_total=len(plan.checks),
            checks_passed=0, checks_failed=failed, shippable=False, verified_at=time.time(), models=MODELS))
        tracer.log("system", "Report ready",
                   f"score {report.score}/100 · {sum(1 for f in findings if f.status == 'open')} open findings", status="ok")
        s.report, s.memo, s.shipped_at = report, "", 0
        save_session(s)
        tracer.finish()
        return report
    except Exception as exc:
        tracer.finish(f"{type(exc).__name__}: {exc}")
        raise


# ---------- regeneration loop ----------

def _find(s: Session, finding_id: str) -> Finding:
    if not s.report:
        raise ValueError("Run verification first.")
    for f in s.report.findings:
        if f.id == finding_id:
            return f
    raise KeyError(f"finding '{finding_id}' not found")


async def regenerate(session_id: str, finding_id: str, run_id: str, apply_to_draft: bool = False) -> Report:
    tracer = Tracer(run_id, "regenerate")
    try:
        s = load_session(session_id)
        f = _find(s, finding_id)
        if not f.can_regenerate:
            raise ValueError("Narrative findings require an editor decision, not image regeneration.")
        canon = canon_mod.load(s.canon_id)
        check = next(c for c in s.report.plan.checks if c.check_id == f.check_id)
        panel = next(p for p in s.draft.panels if p.id == f.panel_id)
        ref_asset = reference_asset(canon, f.reference_label)
        mismatches = "\n".join(f"- {m.trait}: draft shows '{m.draft}', canon requires '{m.canon}'" for m in f.mismatches) or "- see instruction"
        observation = ""
        for attempt in range(1, config.REGEN_MAX_ATTEMPTS + 1):
            prompt = prompts.REGENERATE.format(character=f.character, reference_label=f.reference_label,
                                               mismatches=mismatches, fix=f.suggested_fix)
            if attempt > 1:
                prompt += prompts.REGENERATE_RETRY.format(attempt=attempt, observation=observation)
            async with tracer.span("Nano Banana · regenerate", f"Repainting {panel.ref} (attempt {attempt}/{config.REGEN_MAX_ATTEMPTS})",
                                   model=config.MODEL_IMAGE) as sp:
                data, mime = await llm.generate_image([llm.text_part(prompt), llm.image_part(panel.image), llm.image_part(ref_asset)])
                new_ref = store.assets().put(data, mime)
                sp["detail"] = "new panel generated"
            async with tracer.span("Flash · re-verify", f"Checking the new panel against {f.reference_label}",
                                   model=config.MODEL_SUBAGENT) as sp:
                v = await check_image(check, canon, new_ref, panel.ref + " (regenerated)")
                obs = "; ".join(f"{o.trait}: reference {o.canon_image} / new {o.draft_image}" for o in v.observations)
                sp["detail"] = ("PASS — " if v.consistent else "FAIL — ") + (obs or v.explanation)
                sp["status"] = "ok" if v.consistent else "error"
            f.regenerated_image, f.regen_attempts = new_ref, attempt
            if v.consistent:
                f.status = "resolved"
                f.resolution_note = f"Regenerated and re-verified on attempt {attempt}/{config.REGEN_MAX_ATTEMPTS}."
                if apply_to_draft:
                    panel.image = new_ref
                break
            observation = obs or v.explanation
        else:
            f.resolution_note = f"Still inconsistent after {config.REGEN_MAX_ATTEMPTS} attempts — needs the artist."
            f.needs_human = True
        scoring.recompute(s.report)
        save_session(s)
        tracer.finish()
        return s.report
    except Exception as exc:
        tracer.finish(f"{type(exc).__name__}: {exc}")
        raise


def apply_fix(session_id: str, finding_id: str) -> Session:
    s = load_session(session_id)
    f = _find(s, finding_id)
    if f.status != "resolved" or not f.regenerated_image:
        raise ValueError("Only a resolved regeneration can be applied.")
    for p in s.draft.panels:
        if p.id == f.panel_id:
            p.image = f.regenerated_image
    save_session(s)
    return s


def decide(session_id: str, finding_id: str, action: str, note: str = "") -> Report:
    s = load_session(session_id)
    f = _find(s, finding_id)
    if action not in ("dismiss", "keep", "send_back", "reopen"):
        raise ValueError("action must be dismiss | keep | send_back | reopen")
    f.decision = Decision(action=action, note=note, at=time.time())
    f.status = "dismissed" if action == "dismiss" else "open"
    scoring.recompute(s.report)
    save_session(s)
    return s.report


def ship(session_id: str) -> Session:
    s = load_session(session_id)
    if not s.report or not s.report.shippable:
        raise ValueError("Unresolved critical findings block shipping.")
    s.shipped_at = time.time()
    save_session(s)
    return s


# ---------- editor memo (Argon long decode) ----------

async def memo(session_id: str, run_id: str) -> str:
    tracer = Tracer(run_id, "memo")
    try:
        s = load_session(session_id)
        if not s.report:
            raise ValueError("Run verification first.")
        canon = canon_mod.load(s.canon_id)
        report = s.report.model_dump(exclude={"plan"})
        panels = "\n".join(f"{p.ref}: {p.caption} | {p.dialogue}" for p in s.draft.panels)
        async with tracer.span("Argon · memo", "Writing the continuity editor's memo", model=config.MODEL_ORCHESTRATOR) as sp:
            res = await canon_mod.chained(canon, config.MODEL_ORCHESTRATOR, [llm.text_part(prompts.MEMO.format(
                episode=s.draft.episode, title=s.draft.title, report=json.dumps(report, default=str)[:60000], panels=panels))],
                tracer, thinking="medium", max_output_tokens=8000)
            sp["detail"] = f"{len(res.text.split()):,} words"
            sp["tokens"] = res.output_tokens
        s.memo = res.text
        save_session(s)
        tracer.finish()
        return s.memo
    except Exception as exc:
        tracer.finish(f"{type(exc).__name__}: {exc}")
        raise


# ---------- draft parsing (multimodal) ----------

class ParsedPanel(BaseModel):
    index: int
    caption: str
    dialogue: str
    image_index: int = -1


class DraftParse(BaseModel):
    title: str = ""
    panels: list[ParsedPanel]


async def parse_draft(episode: int, title: str, text: str, images: list[str]) -> Draft:
    parts = [llm.text_part(prompts.PARSE_DRAFT)]
    if text.strip():
        parts.append(llm.text_part(f"SCRIPT:\n{text}"))
    for i, ref in enumerate(images):
        parts.append(llm.text_part(f"[image {i}]"))
        parts.append(llm.media_part(ref))
    res = await llm.generate(config.MODEL_SUBAGENT, parts, schema=DraftParse, thinking="medium")
    panels = []
    for n, p in enumerate(sorted(res.parsed.panels, key=lambda x: x.index), start=1):
        img = images[p.image_index] if 0 <= p.image_index < len(images) else ""
        panels.append(Panel(id=f"p{n}", index=n, image=img, caption=p.caption, dialogue=p.dialogue))
    return Draft(episode=episode, title=title or res.parsed.title, panels=panels)
