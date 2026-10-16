"""Build the demo canon with Gemini 4 Argon from the full seed corpus and save it to seed/demo_canon.json.

Usage: python -m scripts.build_demo_canon
"""
import asyncio
import json
import uuid

from canonkeeper import canon as canon_mod, config, store
from canonkeeper.trace import Tracer


async def main() -> None:
    run_id = uuid.uuid4().hex
    tracer = Tracer(run_id, "canon_build")
    canon = await canon_mod.build(config.DEMO_CANON_ID, canon_mod.seed_corpus(), tracer, "seed")
    tracer.finish()
    (config.SEED_DIR / "demo_canon.json").write_text(canon.model_dump_json(indent=2), encoding="utf-8")
    for step in store.docs().get("runs", run_id)["steps"]:
        if step["status"] != "running":
            print(f"[{step['t_ms'] / 1000:6.1f}s] {step['actor']:<28} {step['action']} — {step['detail']}")
    b = canon.bible
    print(json.dumps({
        "input_tokens": canon.context.input_tokens, "build_seconds": canon.build_seconds,
        "characters": [(c.name, c.status, c.status_since_episode, [(t.name, t.side) for t in c.traits if t.side != "none"],
                        c.reference_labels) for c in b.characters],
        "events": len(b.events), "threads": [(t.id, t.resolved) for t in b.threads],
        "verification": canon.verification.model_dump(),
    }, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
