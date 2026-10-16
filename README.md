# CanonKeeper

**CanonKeeper lets a webtoon continuity editor verify a new chapter against the entire back catalogue at once — Gemini 4 Argon holds the full series in its 1M-token context, orchestrates parallel multimodal verification agents, repaints visual errors and re-checks its own fixes, and leaves story judgment calls to the human.**

Track 1 — Gemini 4 Argon in entertainment.

---

## The problem

Korean webtoons run for hundreds of episodes on weekly deadlines. By chapter 50+, continuity lives in an editor's memory and a spreadsheet: which cheek the hero's scar is on, who is dead, which relic was destroyed, which foreshadowing is still open. Readers notice every slip — and the slips that hurt most span the whole series (a scar set in EP3, a death in EP7, a draft in EP13).

**Target user:** the continuity editor / PD who signs off each chapter before it ships.

## Why this needs Gemini 4 Argon

Retrieval that chunks a series per episode structurally cannot see contradictions that span the series. CanonKeeper keeps the **whole series in one Argon context** and reuses it for every decision:

| Argon capability | Where it is load-bearing |
|---|---|
| **1M unified context** | The canon builder reads every episode script plus reference art in one request (demo series: **95,428 input tokens, measured**). That interaction is kept and chained (`previous_interaction_id`) so the planner, adjudicator and memo all reason over the full series. |
| **Multimodal orchestration** | The planner *looks at every draft panel* to identify who is in it — characters can appear in the art without being named in the script — and dispatches the right agents with the exact canon facts they need. |
| **Frontier reasoning** | The adjudicator cross-examines every subagent finding against the full series: confirm, reject as a false positive, or hand to the editor — always with a verbatim quote and episode. |
| **Long decode** | The editor memo: a full continuity report with citations, recommended rewrites and threads to watch. |

No detection rules are hardcoded. What to check, which reference to compare against and whether something is a real contradiction are all decided by the models; the only code-side logic is the score arithmetic and the ship gate.

## How it works

```
 back catalogue (scripts, page art, reference images)
        │
        ▼
 Argon · CANON BUILDER ──► canon bible with verbatim evidence ──► Flash · CITATION CHECK ──► Argon · REPAIR (if needed)
        │  interaction kept as the series context
        ▼
 draft chapter (panel art + captions + dialogue)
        │
        ├─► Argon · PLANNER        reads every panel image, identifies characters, plans checks + canon briefs
        ├─► Flash agents (parallel)
        │      appearance    multimodal: draft panel vs canon reference image (scar side, hair, eyes, outfit, items)
        │      lifeline      multimodal: dead characters present, destroyed items back, timeline breaks
        │      foreshadowing setup/payoff threads
        ├─► Argon · ADJUDICATOR    confirm / reject / needs_human, with evidence quotes
        ├─► score + ship gate      (deterministic)
        │
        ├─► visual finding    → Nano Banana REPAINT → Flash RE-VERIFY → retry ≤3   (closed loop)
        └─► narrative finding → EDITOR decision (dismiss as intentional / keep / send back)   (human in the loop)
```

Every step is streamed to the UI as a live agent trace.

### Verification loops

1. **Canon citation check** — every fact in the bible must be backed by a verbatim quote; Flash audits each quote against the source episode, Argon repairs unsupported facts from the context it already holds. Demo canon: **18/18 facts verified**.
2. **Adjudication** — subagent findings are confirmed or overruled by Argon with evidence from the full series.
3. **Repaint → re-verify** — visual errors are repainted by Nano Banana and re-checked by the appearance agent against the canon reference until they pass (max 3 attempts).
4. **Human in the loop** — story decisions (is this dead character a vision?) are never auto-resolved; the chapter cannot ship while critical findings are open.

## Models

| Job | Model |
|---|---|
| Canon builder, planner, adjudicator, memo | `gemini-4-argon` |
| Parallel verification agents, citation checks, draft parsing | `gemini-3.8-flash` |
| Panel repainting | `gemini-nano-banana-2.1` |

## Try it

1. Open the app — the demo series *Chronicles of the Starfall Blade* (12 episodes) is loaded as canon and the EP13 draft is on the desk.
2. **Run verification** and watch the agent trace: Argon reads the panels, plans checks, the agents run in parallel, Argon adjudicates.
3. **Regenerate & re-verify** the visual finding — red to green when the repaint passes.
4. Decide the narrative finding as the editor, then **Ship**.
5. **Edit draft** — change any caption, dialogue or panel art and verify again. Nothing is pre-scripted.
6. **Editor memo** — Argon writes the full continuity memo.

## Architecture

- **Backend:** FastAPI on Cloud Run, stateless. Sessions, canons and run traces in **Firestore**; uploaded and generated art in **Cloud Storage** — any instance can serve any request, so the service scales horizontally.
- **Agent registry:** each verification agent declares what it checks; the planner reads the registry, so adding a new kind of check is one registered agent.
- **Large catalogues:** above ~700K estimated tokens the canon is built in volumes and merged by Argon.
- **Frontend:** static HTML/CSS/JS served by the same service.

```
backend/
  canonkeeper/
    api.py         HTTP API
    pipeline.py    plan → parallel agents → adjudicate → score; repaint loop; decisions; memo; draft parsing
    canon.py       canon builder, citation check, series context chaining
    agents/        appearance, lifeline, foreshadowing (registry)
    prompts.py     all prompts
    store.py       Firestore / Cloud Storage (in-memory for local dev)
    trace.py       live agent trace
  scripts/         corpus generation, demo canon build, end-to-end run
  seed/            demo series: 12-episode corpus, reference art, EP13 draft
  static/          web app
```

## Demo data

*Chronicles of the Starfall Blade* is a synthetic series created for this project: episode outlines were expanded into full panel-by-panel scripts by Gemini 4 Argon (`scripts/generate_corpus.py`, ~387K characters), and the panels were drawn with Nano Banana. The demo canon in `seed/demo_canon.json` was built from that corpus by the canon builder (`scripts/build_demo_canon.py`).

## Run locally

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "GOOGLE_API_KEY=..." > .env
CK_STORE=memory .venv/bin/uvicorn canonkeeper.api:app --reload
```

## Deploy

```bash
gcloud run deploy canonkeeper-v2 --source . --region asia-northeast3 --allow-unauthenticated \
  --set-env-vars GOOGLE_API_KEY=...,CK_STORE=gcp --timeout 900 --memory 2Gi --cpu 2
```

## Roadmap

Batch verification of a whole season, publisher CMS integration, per-studio canon workspaces with auth, and style-consistency checks for background art.

## License

MIT
