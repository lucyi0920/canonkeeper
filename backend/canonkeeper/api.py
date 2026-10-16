"""HTTP API. Long operations (verify, regenerate, memo, canon build) take a client-chosen run_id;
the client polls GET /api/runs/{run_id} for the live agent trace while the request runs."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import canon as canon_mod, config, pipeline, store
from .canon import Corpus, CorpusEpisode
from .schemas import Draft, ReferenceImage
from .trace import Tracer

app = FastAPI(title="CanonKeeper API")


@app.exception_handler(KeyError)
async def _not_found(_: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"error": str(exc).strip("'\"")})


@app.exception_handler(ValueError)
async def _bad_request(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(Exception)
async def _server_error(_: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


# ---------- meta ----------

@app.get("/api/health")
async def health():
    return {"status": "ok", "models": pipeline.MODELS, "store": config.STORE_BACKEND,
            "agents": [{"name": a.name, "model": a.model, "dimension": a.dimension}
                       for a in pipeline.agents.REGISTRY.values()]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = store.docs().get("runs", run_id)
    if run is None:
        return {"run_id": run_id, "status": "pending", "steps": []}
    return run


# ---------- assets ----------

class AssetIn(BaseModel):
    data_url: str


@app.post("/api/assets")
async def upload_asset(body: AssetIn):
    data, mime = store.decode_data_url(body.data_url)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large ({len(data) // 1024} KB, max {config.MAX_UPLOAD_BYTES // 1024} KB)")
    if not (mime.startswith("image/") or mime == "application/pdf"):
        raise ValueError(f"unsupported file type {mime}")
    return {"ref": store.assets().put(data, mime), "mime": mime}


@app.get("/api/assets/{ref}")
async def get_asset(ref: str):
    data, mime = store.assets().get(ref)
    return Response(content=data, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


# ---------- canon ----------

@app.get("/api/canons/{canon_id}")
async def get_canon(canon_id: str):
    return canon_mod.load(canon_id).model_dump()


@app.get("/api/demo/corpus")
async def demo_corpus():
    c = canon_mod.seed_corpus()
    return c.model_dump()


class BuildIn(BaseModel):
    run_id: str
    series_title: str = ""
    episodes: list[CorpusEpisode] = []
    references: list[ReferenceImage] = []
    use_demo_corpus: bool = False


@app.post("/api/canons/build")
async def build_canon(body: BuildIn):
    if body.use_demo_corpus:
        corpus, corpus_asset, prefix = canon_mod.seed_corpus(), "seed", "rebuilt"
    else:
        if not body.episodes:
            raise ValueError("Add at least one episode.")
        if sum(len(e.script) for e in body.episodes) > config.MAX_CORPUS_CHARS:
            raise ValueError("Corpus too large.")
        if len(body.references) > config.MAX_REFERENCES:
            raise ValueError("Too many reference images.")
        corpus = Corpus(series_title=body.series_title or "Untitled series",
                        episodes=sorted(body.episodes, key=lambda e: e.episode), references=body.references)
        corpus_asset = store.assets().put(corpus.model_dump_json().encode(), "application/json")
        prefix = "canon"
    tracer = Tracer(body.run_id, "canon_build")
    try:
        canon = await canon_mod.build(f"{prefix}-{uuid.uuid4().hex[:12]}", corpus, tracer, corpus_asset)
        tracer.finish()
        return canon.model_dump()
    except Exception as exc:
        tracer.finish(f"{type(exc).__name__}: {exc}")
        raise


# ---------- sessions ----------

class SessionIn(BaseModel):
    canon_id: str = config.DEMO_CANON_ID
    draft: Optional[Draft] = None


@app.post("/api/sessions")
async def new_session(body: SessionIn):
    return pipeline.create_session(body.canon_id, body.draft).model_dump()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return pipeline.load_session(session_id).model_dump()


class DraftIn(BaseModel):
    draft: Draft


@app.put("/api/sessions/{session_id}/draft")
async def put_draft(session_id: str, body: DraftIn):
    if len(body.draft.panels) > config.MAX_PANELS:
        raise ValueError(f"max {config.MAX_PANELS} panels")
    return pipeline.update_draft(session_id, body.draft).model_dump()


class RunIn(BaseModel):
    run_id: str


@app.post("/api/sessions/{session_id}/verify")
async def verify(session_id: str, body: RunIn):
    return (await pipeline.verify(session_id, body.run_id)).model_dump()


@app.post("/api/sessions/{session_id}/findings/{finding_id}/regenerate")
async def regenerate(session_id: str, finding_id: str, body: RunIn):
    return (await pipeline.regenerate(session_id, finding_id, body.run_id)).model_dump()


@app.post("/api/sessions/{session_id}/findings/{finding_id}/apply")
async def apply_fix(session_id: str, finding_id: str):
    return pipeline.apply_fix(session_id, finding_id).model_dump()


class DecisionIn(BaseModel):
    action: str
    note: str = ""


@app.post("/api/sessions/{session_id}/findings/{finding_id}/decision")
async def decision(session_id: str, finding_id: str, body: DecisionIn):
    return pipeline.decide(session_id, finding_id, body.action, body.note).model_dump()


@app.post("/api/sessions/{session_id}/memo")
async def memo(session_id: str, body: RunIn):
    return {"memo": await pipeline.memo(session_id, body.run_id)}


@app.post("/api/sessions/{session_id}/ship")
async def ship(session_id: str):
    return pipeline.ship(session_id).model_dump()


class ParseIn(BaseModel):
    episode: int = 1
    title: str = ""
    text: str = ""
    images: list[str] = []


@app.post("/api/parse")
async def parse(body: ParseIn):
    if not body.text.strip() and not body.images:
        raise ValueError("Paste a script or attach panel art.")
    return (await pipeline.parse_draft(body.episode, body.title, body.text, body.images)).model_dump()


# ---------- frontend ----------

if config.STATIC_DIR.is_dir():
    if (config.STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=config.STATIC_DIR / "assets"), name="static-assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        target = config.STATIC_DIR / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(config.STATIC_DIR / "index.html")
