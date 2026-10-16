"""Canon: building the bible from a full back catalogue and keeping the series in Argon's context."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from pydantic import BaseModel

from . import config, llm, prompts, store
from .schemas import (Canon, CanonBible, CanonContext, CanonVerification, EpisodeMeta, Evidence,
                      ReferenceImage)
from .trace import Tracer


# ---------- corpus ----------

class CorpusEpisode(BaseModel):
    episode: int
    title: str = ""
    script: str = ""
    images: list[str] = []     # asset refs of page art / PDFs for this episode


class Corpus(BaseModel):
    series_title: str
    episodes: list[CorpusEpisode]
    references: list[ReferenceImage]


def seed_corpus() -> Corpus:
    outline = json.loads((config.SEED_DIR / "source_outline.json").read_text(encoding="utf-8"))
    eps = []
    for e in outline["represented_episodes"]:
        path = config.SEED_DIR / "corpus" / f"ep{e['episode']:02d}.md"
        eps.append(CorpusEpisode(episode=e["episode"], title=e["title"],
                                 script=path.read_text(encoding="utf-8") if path.exists() else e["script"]))
    refs = [
        ReferenceImage(label="EP3 panel 2", character="Jin", episode=3, asset="seed:ep3_panel2_jin.jpg"),
        ReferenceImage(label="EP7 panel 4", character="Mira", episode=7, asset="seed:ep7_panel4_mira.jpg"),
        ReferenceImage(label="Jin character sheet", character="Jin", episode=3, asset="seed:jin_ref.jpg"),
    ]
    return Corpus(series_title=outline["series_title"], episodes=eps, references=refs)


def load_corpus(canon: Canon) -> Corpus:
    if canon.corpus_asset == "seed":
        return seed_corpus()
    data, _ = store.assets().get(canon.corpus_asset)
    return Corpus.model_validate_json(data)


def corpus_parts(corpus: Corpus, episodes: Optional[list[CorpusEpisode]] = None) -> list[dict]:
    parts = [llm.text_part(f"SERIES: {corpus.series_title}")]
    for ep in episodes if episodes is not None else corpus.episodes:
        parts.append(llm.text_part(f"=== EPISODE {ep.episode}: {ep.title} ===\n{ep.script}"))
        for ref in ep.images:
            parts.append(llm.text_part(f"[EPISODE {ep.episode} page art]"))
            parts.append(llm.media_part(ref))
    for r in corpus.references:
        parts.append(llm.text_part(f"REFERENCE IMAGE — label: {r.label} — character: {r.character or 'unspecified'} — episode: {r.episode or 'n/a'}"))
        parts.append(llm.image_part(r.asset))
    return parts


def estimate_tokens(corpus: Corpus) -> int:
    chars = sum(len(e.script) for e in corpus.episodes)
    images = sum(len(e.images) for e in corpus.episodes) + len(corpus.references)
    return chars // 4 + images * 1300


# ---------- persistence ----------

def load(canon_id: str) -> Canon:
    doc = store.docs().get("canons", canon_id)
    if doc is None:
        if canon_id == config.DEMO_CANON_ID:
            return install_demo()
        raise KeyError(f"canon '{canon_id}' not found")
    return Canon.model_validate(doc)


def save(canon: Canon) -> None:
    store.docs().set("canons", canon.canon_id, canon.model_dump())


def install_demo() -> Canon:
    """Loads the Argon-built demo canon shipped in seed/demo_canon.json (produced by scripts.build_demo_canon)."""
    path = config.SEED_DIR / "demo_canon.json"
    if not path.exists():
        raise KeyError("demo canon not built yet — run `python -m scripts.build_demo_canon`")
    canon = Canon.model_validate_json(path.read_text(encoding="utf-8"))
    save(canon)
    return canon


# ---------- context ----------

async def refresh_context(canon: Canon, tracer: Optional[Tracer] = None) -> Canon:
    corpus = load_corpus(canon)
    parts = [llm.text_part(prompts.CONTEXT_PRIME), *corpus_parts(corpus),
             llm.text_part("CANON BIBLE:\n" + canon.bible.model_dump_json())]
    if tracer:
        async with tracer.span("Argon · context", "Loading the full series into context",
                               model=config.MODEL_ORCHESTRATOR) as s:
            res = await llm.generate(config.MODEL_ORCHESTRATOR, parts, thinking="low")
            s["detail"] = f"{res.input_tokens:,} tokens in context"
            s["tokens"] = res.input_tokens
    else:
        res = await llm.generate(config.MODEL_ORCHESTRATOR, parts, thinking="low")
    canon.context = CanonContext(interaction_id=res.interaction_id, model=config.MODEL_ORCHESTRATOR,
                                 input_tokens=res.input_tokens or canon.context.input_tokens,
                                 created_at=time.time(), mode=canon.context.mode)
    save(canon)
    return canon


async def chained(canon: Canon, model: str, parts: list[dict], tracer: Optional[Tracer] = None, **kwargs) -> llm.Result:
    """Runs a request on top of the series context held by Argon (previous_interaction_id).
    If the stored context has expired, the full corpus is re-sent once and the context refreshed."""
    if not canon.context.interaction_id:
        canon = await refresh_context(canon, tracer)
    try:
        return await llm.generate(model, parts, previous=canon.context.interaction_id, **kwargs)
    except Exception as exc:
        if tracer:
            tracer.log("system", "Series context expired — reloading", str(exc)[:200], status="info")
        canon = await refresh_context(canon, tracer)
        return await llm.generate(model, parts, previous=canon.context.interaction_id, **kwargs)


# ---------- builder ----------

class CitationResult(BaseModel):
    fact_id: str
    supported: bool
    corrected_quote: str = ""
    note: str = ""


class CitationResults(BaseModel):
    results: list[CitationResult]


async def _check_citations(bible: CanonBible, corpus: Corpus, only: Optional[set[str]] = None) -> dict[str, CitationResult]:
    by_ep: dict[int, list[Evidence]] = {}
    for ev in bible.evidence:
        if only is None or ev.fact_id in only:
            by_ep.setdefault(ev.episode, []).append(ev)
    scripts = {e.episode: e.script for e in corpus.episodes}
    sem = asyncio.Semaphore(config.SUBAGENT_CONCURRENCY)

    async def one(ep: int, items: list[Evidence]) -> list[CitationResult]:
        text = scripts.get(ep)
        if not text:
            return [CitationResult(fact_id=i.fact_id, supported=False, note=f"episode {ep} not in corpus") for i in items]
        claims = "\n".join(f'- fact_id={i.fact_id}: {i.fact} | quote: "{i.quote}"' for i in items)
        async with sem:
            res = await llm.generate(config.MODEL_SUBAGENT, [
                llm.text_part(prompts.CITATION_CHECK),
                llm.text_part(f"EPISODE {ep} TEXT:\n{text}"),
                llm.text_part(f"CLAIMS:\n{claims}")], schema=CitationResults, thinking="low")
        return res.parsed.results

    results = await asyncio.gather(*(one(ep, items) for ep, items in by_ep.items()))
    return {r.fact_id: r for batch in results for r in batch}


def _apply_citations(bible: CanonBible, checked: dict[str, CitationResult]) -> list[Evidence]:
    failed = []
    for ev in bible.evidence:
        r = checked.get(ev.fact_id)
        if r is None:
            continue
        if r.supported:
            ev.verified = True
            if r.corrected_quote:
                ev.quote = r.corrected_quote
        else:
            ev.verified = False
            failed.append(ev)
    return failed


async def build(canon_id: str, corpus: Corpus, tracer: Tracer, corpus_asset: str) -> Canon:
    t0 = time.time()
    est = estimate_tokens(corpus)
    tracer.log("system", "Corpus received",
               f"{len(corpus.episodes)} episodes, {len(corpus.references)} reference images, ≈{est:,} tokens (estimate)")

    if est <= config.VOLUME_TOKEN_BUDGET:
        async with tracer.span("Argon · canon builder", "Reading the whole series in one context",
                               model=config.MODEL_ORCHESTRATOR) as s:
            res = await llm.generate(config.MODEL_ORCHESTRATOR,
                                     [llm.text_part(prompts.CANON_BUILD), *corpus_parts(corpus)],
                                     schema=CanonBible, thinking="medium")
            s["detail"] = (f"{res.input_tokens:,} tokens read · {len(res.parsed.characters)} characters, "
                           f"{len(res.parsed.events)} events, {len(res.parsed.threads)} threads")
            s["tokens"] = res.input_tokens
        bible, ctx_id, measured, mode = res.parsed, res.interaction_id, res.input_tokens, "single"
    else:
        bible, ctx_id, measured = await _build_in_volumes(corpus, tracer)
        mode = "volumes"

    total = len(bible.evidence)
    async with tracer.span("Flash · citation check", f"Verifying {total} cited facts against the source",
                           model=config.MODEL_SUBAGENT) as s:
        failed = _apply_citations(bible, await _check_citations(bible, corpus))
        s["detail"] = f"{total - len(failed)}/{total} facts supported by verbatim source quotes"

    repaired = 0
    if failed and mode == "single":
        listing = "\n".join(f"- {e.fact_id}: {e.fact} (EP{e.episode}) quote: \"{e.quote}\"" for e in failed)
        async with tracer.span("Argon · repair", f"Re-deriving {len(failed)} unsupported facts from the context",
                               model=config.MODEL_ORCHESTRATOR) as s:
            fix = await llm.generate(config.MODEL_ORCHESTRATOR,
                                     [llm.text_part(prompts.CANON_REPAIR.format(failures=listing))],
                                     schema=CanonBible, previous=ctx_id, thinking="medium")
            bible, ctx_id = fix.parsed, fix.interaction_id
            # the repaired bible is a fresh document: verify every citation again
            still = _apply_citations(bible, await _check_citations(bible, corpus))
            repaired = max(0, len(failed) - len(still))
            s["detail"] = f"{repaired} repaired, {len(still)} still unsupported"

    verified = sum(1 for e in bible.evidence if e.verified)
    canon = Canon(
        canon_id=canon_id, series_title=corpus.series_title or bible.series_title, bible=bible,
        episodes=[EpisodeMeta(episode=e.episode, title=e.title, chars=len(e.script), images=len(e.images))
                  for e in corpus.episodes],
        references=corpus.references, corpus_asset=corpus_asset,
        context=CanonContext(interaction_id=ctx_id, model=config.MODEL_ORCHESTRATOR, input_tokens=measured,
                             token_source="measured" if measured else "estimate", created_at=time.time(), mode=mode),
        verification=CanonVerification(total=len(bible.evidence), verified=verified, repaired=repaired),
        build_seconds=round(time.time() - t0, 1), built_at=time.time(),
    )
    save(canon)
    tracer.log("system", "Canon ready", f"{verified}/{len(bible.evidence)} facts verified · {canon.build_seconds}s", status="ok")
    return canon


async def _build_in_volumes(corpus: Corpus, tracer: Tracer) -> tuple[CanonBible, str, int]:
    volumes: list[list[CorpusEpisode]] = [[]]
    budget = 0
    for ep in corpus.episodes:
        cost = len(ep.script) // 4 + len(ep.images) * 1300
        if volumes[-1] and budget + cost > config.VOLUME_TOKEN_BUDGET:
            volumes.append([])
            budget = 0
        volumes[-1].append(ep)
        budget += cost

    async def one(i: int, eps: list[CorpusEpisode]) -> llm.Result:
        async with tracer.span("Argon · canon builder", f"Volume {i + 1}/{len(volumes)}: EP{eps[0].episode}–EP{eps[-1].episode}",
                               model=config.MODEL_ORCHESTRATOR) as s:
            r = await llm.generate(config.MODEL_ORCHESTRATOR,
                                   [llm.text_part(prompts.CANON_BUILD), *corpus_parts(corpus, eps)],
                                   schema=CanonBible, thinking="medium")
            s["detail"] = f"{r.input_tokens:,} tokens read"
            s["tokens"] = r.input_tokens
            return r

    parts = await asyncio.gather(*(one(i, v) for i, v in enumerate(volumes)))
    async with tracer.span("Argon · merge", f"Merging {len(parts)} volume bibles", model=config.MODEL_ORCHESTRATOR) as s:
        merged = await llm.generate(config.MODEL_ORCHESTRATOR, [
            llm.text_part(prompts.CANON_MERGE),
            *[llm.text_part(f"VOLUME {i + 1}:\n{p.parsed.model_dump_json()}") for i, p in enumerate(parts)]],
            schema=CanonBible, thinking="medium")
        s["detail"] = f"{len(merged.parsed.characters)} characters, {len(merged.parsed.threads)} threads"
    return merged.parsed, merged.interaction_id, sum(p.input_tokens for p in parts)
