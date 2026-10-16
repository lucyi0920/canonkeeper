"""Generate the full-length demo back catalogue (EP1-EP12) with Gemini 4 Argon.

The demo series is synthetic. Each episode outline in seed/source_outline.json is
expanded by Argon (long decode) into a complete panel-by-panel webtoon script,
written to seed/corpus/epNN.md. The canon builder later reads this corpus.

Usage: python -m scripts.generate_corpus [--episodes 1,2,3] [--force]
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "seed"
OUT = SEED / "corpus"
load_dotenv(ROOT / ".env")

MODEL = "gemini-4-argon"

PROMPT = """You are the head writer of the serialized Korean fantasy webtoon "{title}".
Write the COMPLETE production script for Episode {episode}: "{ep_title}".

Format (plain Markdown, no preamble):
# Episode {episode} — {ep_title}
Then 40-60 panels. For each panel:
## Panel N
**Visual:** a precise art direction paragraph (characters present, their appearance, framing, setting, lighting).
**Dialogue:** lines as `Speaker: "line"` (or `(no dialogue)`), plus narration boxes as `Narration: "..."`.

Hard continuity rules — the episode must agree with ALL of these established facts:
{facts}

What happens in this episode (outline — expand it, keep every event, add texture, side characters, banter, worldbuilding):
{outline}

Mandatory establishing panels in this episode (reproduce them faithfully, with these panel numbers):
{anchors}

Write the whole episode. Target length: 4,500-6,000 words. Do not summarize, do not skip panels."""


def facts_for(outline: dict, episode: int) -> str:
    bible = outline["ground_truth_bible"]
    lines = []
    for c in bible["characters"]:
        traits = "; ".join(f"{k}: {v}" for k, v in c["traits"].items())
        status = c["status"]
        if status == "dead" and c.get("status_since_episode"):
            if episode < c["status_since_episode"]:
                status = f"alive (dies in EP{c['status_since_episode']})"
            elif episode == c["status_since_episode"]:
                status = "dies in this episode"
            else:
                status = f"dead since EP{c['status_since_episode']} — must not appear alive except clearly framed memories"
        lines.append(f"- {c['name']} — {status}. {traits}")
    for e in bible["events"]:
        lines.append(f"- EP{e['episode']} ({e['kind']}): {e['description']}")
    for t in bible["threads"]:
        lines.append(f"- Thread {t['id']} (set up EP{t['setup_episode']}, resolved={t['resolved']}): {t['description']}")
    lines.append("- Before EP3, Jin's face is completely unscarred. From EP3 on, his X-shaped crimson scar is on the VIEWER'S LEFT cheek in every front-facing panel.")
    lines.append("- LEFT/RIGHT in art direction always means the viewer's perspective (side of the image canvas).")
    return "\n".join(lines)


def generate(client, outline: dict, ep: dict, force: bool) -> str:
    path = OUT / f"ep{ep['episode']:02d}.md"
    if path.exists() and not force:
        return f"EP{ep['episode']}: exists, skipped"
    anchors = "\n".join(
        f"- Panel {p['panel']}: {p['caption']} Dialogue: {p['dialogue']}" for p in ep.get("panels", [])
    ) or "- (none)"
    prompt = PROMPT.format(
        title=outline["series_title"], episode=ep["episode"], ep_title=ep["title"],
        facts=facts_for(outline, ep["episode"]), outline=ep["script"], anchors=anchors,
    )
    t = time.time()
    for attempt in range(3):
        try:
            res = client.interactions.create(
                model=MODEL, input=prompt,
                generation_config={"thinking_level": "low", "max_output_tokens": 16000},
            )
            text = (res.output_text or "").strip()
            if len(text) < 8000:
                raise RuntimeError(f"too short ({len(text)} chars)")
            path.write_text(text + "\n", encoding="utf-8")
            return f"EP{ep['episode']}: {len(text):,} chars in {time.time() - t:.0f}s"
        except Exception as exc:  # retry transient failures
            err = exc
            time.sleep(3)
    return f"EP{ep['episode']}: FAILED — {err}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    outline = json.loads((SEED / "source_outline.json").read_text(encoding="utf-8"))
    wanted = {int(x) for x in args.episodes.split(",") if x.strip()}
    eps = [e for e in outline["represented_episodes"] if not wanted or e["episode"] in wanted]
    OUT.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for line in pool.map(lambda e: generate(client, outline, e, args.force), eps):
            print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())
