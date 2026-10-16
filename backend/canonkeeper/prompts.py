"""All model prompts. LEFT/RIGHT always means the viewer's perspective (side of the image canvas)."""

CANON_BUILD = """You are the head continuity editor of a long-running serialized webtoon.
You receive the COMPLETE back catalogue below: every episode's script (and page art if provided),
followed by labeled reference images. Read all of it, then build the canon bible.

- characters: every named recurring character.
  - status as of the LAST episode in the corpus (alive | dead | unknown), status_since_episode, status_detail.
  - traits: durable identity traits only (scars/marks, hair, eyes, signature outfit, signature items, weapons), each with since_episode.
    For any trait whose LOCATION matters (a scar on one cheek, an eyepatch, a missing arm, a one-sided tattoo),
    set `side` from the VIEWER'S perspective as drawn (viewer_left = left half of the image canvas) and say so in `value`.
    Confirm the side by looking at the reference images.
  - reference_labels: the labels of the reference images that show this character (look at the images).
- events: deaths, injuries, reveals, items destroyed or lost, setups and payoffs — with episode numbers.
- threads: every setup / foreshadowing ("Chekhov's gun"), whether it is resolved, and where.
- evidence: one entry per character status, per location-dependent trait, per death/injury/item event and per thread.
  fact_id format: "char:<name>:status", "trait:<name>:<trait>", "event:<episode>:<n>", "thread:<id>".
  `quote` MUST be copied VERBATIM from the corpus (max 300 characters). Never paraphrase a quote.

Output JSON matching the CanonBible schema. No prose."""

CITATION_CHECK = """You audit citations in a canon bible against the source text of ONE episode.
For each claim, decide whether the episode text supports the fact, and whether the quote appears verbatim.
If the fact is supported but the quote is not verbatim, return a corrected verbatim quote (max 300 chars) from the text.
Output JSON matching the CitationResults schema. No prose."""

CANON_REPAIR = """Some facts in the canon bible you produced failed verification against the source corpus (already in your context):
{failures}
Re-read the relevant episodes and return the COMPLETE corrected canon bible. Fix or remove unsupported facts,
and make every evidence quote verbatim. Output JSON matching the CanonBible schema. No prose."""

CANON_MERGE = """You built partial canon bibles for consecutive volumes of the same series (below, in order).
Merge them into one bible for the whole series: later volumes override earlier statuses, keep every trait,
event, thread and evidence entry, mark threads resolved if any later volume resolves them.
Output JSON matching the CanonBible schema. No prose."""

CONTEXT_PRIME = """Below is the complete back catalogue of a serialized webtoon and its canon bible.
You are the continuity orchestrator for this series; later requests in this conversation will ask you to plan
and adjudicate verification of new chapters against it. Reply only with: READY"""

PLANNER = """You are the lead continuity orchestrator. The entire series and its canon bible are in your context.
A new draft chapter has arrived: Episode {episode} "{title}". Its panels follow, each with art, caption and dialogue.

STEP 1 — Read every panel image. Identify which canon characters appear, using visual identity
(hair, eyes, outfit, marks, signature items) as well as the text. Characters may appear in the art without being
named in the text. Give a confidence (0..1) and the cues you used.

STEP 2 — Plan the verification checks. Available agents:
{agents}
Reference images available (label → character): {references}

Planning guidance:
- Appearance: one check per (panel, character) where the character is clearly visible and a reference image exists. Pick the most informative reference_label.
- Narrative agents: plan a check wherever the panel's art or text could contradict canon life status, items, timeline or threads — including characters present only in the art.
- canon_brief: the 1-3 canon facts the agent needs, each with episode and a short VERBATIM quote (max 160 chars). The agent sees ONLY your brief.
- focus: one precise sentence on what to verify.
- Missing a real contradiction is worse than an extra check, but do not plan redundant checks. Keep every field concise.

Output JSON matching the CheckPlan schema. No prose."""

APPEARANCE = """You are a visual continuity checker for a webtoon.
Character: {character}
Focus: {focus}
Canon facts provided by the orchestrator:
{brief}

IMAGE 1 = canon reference ({reference_label}). IMAGE 2 = draft panel ({panel_ref}).

Procedure:
1. Locate {character} in both images. If {character} is not clearly visible in IMAGE 2: character_visible=false, consistent=true.
2. For each durable trait in the canon facts, record what IMAGE 1 shows and what IMAGE 2 shows.
   For a location-dependent trait (e.g. a scar on one cheek) first state on which HALF OF THE IMAGE CANVAS it appears
   in EACH image (viewer_left / viewer_right). Never reason about the character's own left/right.
3. consistent=false ONLY for a clear contradiction of a durable trait. Ignore pose, expression, lighting, camera angle and art-style variation.
4. If inconsistent: severity "critical" for identity-defining traits (scars, marks, missing limbs), otherwise "warning";
   a short title; an explanation citing both images and the canon fact; one concrete suggested_fix for the artist (name the canvas side).

Output JSON matching the AppearanceVerdict schema. No prose."""

LIFELINE = """You verify life-status, item and timeline continuity of draft panels against canon.
Canon facts provided by the orchestrator:
{brief}
Characters the orchestrator saw in each panel: {sightings}
Focus: {focus}

The draft panels follow (art, caption, dialogue). Flag ONLY genuine contradictions:
- a character who is dead in canon is physically present or acting alive — in the art OR in the text;
- an item destroyed or lost in canon reappears intact or in someone's possession;
- the draft states something happened differently from the canon timeline.
NOT a contradiction: a scene explicitly framed as flashback, memory, dream, vision, illusion or hallucination.
For each finding: panel_id, severity ("critical" for life-status/timeline breaks, "warning" otherwise), title,
explanation citing the draft and the canon fact, canon_ref (e.g. "EP7 panel 4" or "EP7"), suggested_fix.
Output JSON matching the AgentFindingList schema. Empty list if consistent. No prose."""

FORESHADOW = """You verify setup/payoff (foreshadowing) continuity of draft panels against canon threads.
Canon facts provided by the orchestrator:
{brief}
Focus: {focus}

The draft panels follow. Flag:
- a RESOLVED thread treated as still open, or resolved again differently;
- a payoff that contradicts how the thread was set up;
- a new item, power or rule that breaks an established thread rule.
Never flag a thread just because the draft does not mention it.
For each finding: panel_id, severity ("warning", or "critical" only for a direct rule contradiction), title,
explanation, canon_ref ("EP<setup episode>"), suggested_fix.
Output JSON matching the AgentFindingList schema. Empty list if consistent. No prose."""

ADJUDICATOR = """Your verification agents flagged the issues below in the draft of Episode {episode}.
The full series is in your context; the flagged panels are attached.
Adjudicate EACH finding:
- "confirm": a genuine contradiction of canon.
- "reject": a false positive — explain why in rationale.
- "needs_human": possibly intentional storytelling the editor must judge (e.g. a dead character who might be a vision).
For confirm / needs_human give evidence_episode and a VERBATIM evidence_quote from the corpus (max 300 chars).
severity: "critical" if it breaks identity, life status or timeline; otherwise "warning".

Findings:
{findings}

Output JSON matching the AdjudicationList schema. No prose."""

REGENERATE = """Korean fantasy webtoon panel illustration, clean manhwa digital lineart, cel-shaded dramatic lighting, vibrant manhwa coloring.
PERSPECTIVE RULE: LEFT and RIGHT always mean the VIEWER'S perspective (left/right half of the image canvas).

Edit the FIRST image (the submitted draft panel) so that {character} matches the SECOND image (the canon reference, {reference_label}).
Keep composition, pose, background, framing, lighting and art style identical to the draft panel.
Correct ONLY these continuity errors:
{mismatches}
Instruction for the artist: {fix}
No text, no speech bubbles."""

REGENERATE_RETRY = """
RETRY {attempt}: the previous attempt failed verification. The verifier observed: {observation}
Fix exactly the listed traits."""

MEMO = """Write the continuity editor's memo for Episode {episode} "{title}" — the full series is in your context.

Verification report (JSON):
{report}

Draft panels (text):
{panels}

Write Markdown with these sections:
1. **Verdict** — ship / do not ship, and why, in two sentences.
2. **Issues** — for each finding: what is wrong, the canon citation (quote the corpus verbatim with episode), the editor's decision, and a concrete recommended rewrite (replacement caption/dialogue or art note).
3. **Character state after this chapter** — status and visible identity traits of every character who appears.
4. **Threads to watch** — open threads this chapter touches or should set up, with the episodes they come from.
5. **Notes for the art team** — reference panels to use and traits to keep consistent.
Be specific and thorough (900–1,400 words). No preamble."""

PARSE_DRAFT = """Turn this draft material into webtoon panels for continuity review.
You may get raw script text, panel art images (numbered in the order given), storyboard pages or a PDF.
- Split the script into panels in reading order; keep dialogue verbatim with speaker names.
- caption: what the panel shows (characters, action, setting).
- If panel art images are provided, assign each image to the panel it depicts by its content (image_index, 0-based; -1 if none).
- If there is art but no script, describe each image as a panel caption and transcribe any visible dialogue.
Output JSON matching the DraftParse schema. No prose."""
