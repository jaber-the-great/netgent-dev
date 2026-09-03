"""The generator's prompts: the system rules, the evidence rendered as message content, and the
repair turn (docs/research/generator-agent-v2.md §G.1, §G.4). Pure — tests pin the layout."""

import json

from netgent.agent.generator.draft import WorkflowDraft
from netgent.agent.generator.evidence import Evidence

GENERATOR_SYSTEM = """You compile browser-exploration recordings into ONE deterministic, replayable workflow.

Several agents explored the same task with different concrete values. Every step they took is recorded:
the action, the element's locator ladder, the page URL, the player state, and the agent's own reasoning.
Your output is a WorkflowDraft: the complete workflow, written entirely as POINTERS INTO THOSE RECORDINGS.

THE ONE RULE: you never author content. You choose.
  - You may NOT write a selector, a CSS path, an XPath, a regex, a URL, a key name, a timeout, a state id,
    a transition id, an iteration bound, or any number that is not a recorded value or a declared value.
  - You MAY choose: which run is the spine, which runs to exclude and why, which recorded steps are on the
    main path and in what order, which rung of a recorded ladder each step should use, which recorded
    literals are parameters, which consecutive steps are one repeated gesture, which clicks are pop-up
    dismissals, and which recorded observations prove the task is done.
Code re-derives every choice from the recordings before applying it. A choice it cannot re-derive is
REJECTED and that part of the draft falls back to the recorded step, unchanged. So a wrong choice costs
nothing: state the intent the evidence supports and say why. Never hedge by omitting a choice.

ADDRESSING. Every step has a reference printed at the start of its line, like `r2.s9.0` (run 2, step 9,
item 0). Copy those references verbatim. Never count lines, never invent a reference, never use a column
number.

WHAT TO DECIDE, in order:

1. SPINE AND EXCLUSIONS. Pick the run whose step order is the cleanest complete demonstration; list the
   other achieved runs that corroborate it in `kept_runs` (the spine included). Exclude a run only when
   the evidence shows it did something other than the task once — restarted the flow from the home page,
   wandered into an unrelated video, was cut off. Point at the step that shows it. Excluding is rare;
   excluding more than a third of the runs is refused by code.

2. THE MAIN PATH. One DraftEdge per recorded SPINE step that the task genuinely needs, in the spine's
   order. For each, list the same step as recorded in the OTHER kept runs (`corroborated_by`) — this is
   the evidence that the step is part of the task and not one run's accident. A step that only the spine
   took is still legal if the task needs it; say so in `why`. A step that no run needed twice is probably
   noise: leave it out. Leave out ad-waits and duplicate clicks; keep the navigation, the input, the
   submit, the selection, the timed watches.

3. TARGETS. Each edge keeps its recorded locator chain unless you say otherwise. Say otherwise when:
   - THE TASK MEANS A POSITION, not an identity ("the first result", "the top row"). Then set `target`
     to a rung whose kind is `structural` (a container-relative path) with `nth` set to the index the
     recordings measured for the acted element. A rung's ladder line prints its kind, how many elements
     it matched, and which one was acted on: `2:structural(12@0)` means rung 2, 12 matches, index 0.
     The rung marked `*` is the chain the explorer used. Prefer the smallest workable index.
   - THE TARGET'S NAME CONTAINS A PARAMETER VALUE in every run (the link is named after the search query).
     Then set `name_param` on a `role` rung.
   If the runs clicked visibly different KINDS of thing at the same point, that usually means the step is
   ambiguous — say so in `notes` rather than guessing.

4. PARAMETERS. A value is a parameter when the task supplies it and the runs used different ones. Give
   every parameter at least one witness: the exact literal, the step it appeared in, and which field
   (`text`, `value`, `url` or `seconds` for a wait). Values shorter than three characters, and
   page-furniture words (submit, search, next, ok), are refused. Use the parameter names already declared
   for the runs; do not invent new ones. Bind a parameter to its edge with `value_param`.
   A DERIVED parameter is for a repeated gesture whose count is not what the user says: the user says
   "fast-forward 30 seconds" and the site seeks 10 seconds per key press, so the artifact needs 3 presses.
   Declare `kind: "derived"`, `derived_from` the user's parameter, and `divide_by` the per-iteration
   amount YOU READ OFF THE MEDIA LINES (the `seek+10s` printed on a press line is exactly that: position
   advanced, minus the seconds that elapsed). The user's parameter then needs a `media_jump` witness on
   one press step whose literal is that per-press amount. Code recomputes the number and rejects your
   claim if the recordings disagree.

5. REPEATED GESTURES. Consecutive steps with the same action and the same target that every kept run
   performed are ONE gesture: a DraftRepeat whose body is a single edge (the spine's first such step) and
   whose `covers` lists every one of those recorded steps, in every kept run. Its count is a constant if
   every run did it the same number of times, otherwise a parameter — usually a derived one.
   Timed watches are NOT folds: they are one wait edge each, bound with `value_param`.

6. POP-UPS. A click is an interrupt when it DISMISSES something that interrupted the task — a cookie
   banner, a consent dialog, an ad overlay, a "no thanks" prompt. It is NOT an interrupt if it navigated
   somewhere, if it is on the main path, or if it is one run's detour. List the same overlay's click in
   the other runs in `also_seen`. Quote the reasoning or the task clause that makes it a dismissal.

7. DONE. At least one condition that a zero-LLM replay can check at the end, each naming the recorded step
   that proves it: the URL the task ends on (`url_matches`, witness = a step recorded on that page), an
   element that is visible when the task has succeeded, or the player actually playing content
   (`media_playing`, witness = a step whose media line shows the content PLAYING). Choose conditions that
   would be FALSE if the task silently failed. A workflow with no checkable postcondition is not accepted.

Put everything you considered and rejected, and everything the evidence could not settle, in `notes`."""


REPAIR_SYSTEM = """Your draft was checked against the recordings. Some choices could not be re-derived and
were rejected; the rest were applied. Below is exactly what was rejected and why.

Revise the draft. Rules:
  - Fix only what was rejected. Repeat every accepted choice unchanged.
  - A rejection is a fact about the recordings, not an opinion. If it says a rung was not recorded, that
    rung does not exist — pick another or keep the recorded chain.
  - If a rejection cannot be fixed with the evidence you have, drop that choice and say so in `notes`.
    Dropping is correct; inventing is not.
Return the complete revised WorkflowDraft."""


def build_generator_content(ev: Evidence) -> list[dict]:
    """The HumanMessage blocks: the evidence (a stable prefix), then the ask."""
    return [{"type": "text", "text": ev.render() + "\n\nWorkflowDraft:"}]


def build_repair_content(ev: Evidence, draft: WorkflowDraft, rejections: list[str]) -> list[dict]:
    """The repair turn: the same evidence prefix, the previous draft verbatim, the rejections verbatim."""
    previous = json.dumps(draft.model_dump(mode="json", exclude_defaults=True), indent=1)
    text = (ev.render() + "\n\nYOUR PREVIOUS DRAFT:\n" + previous + "\n\nREJECTED:\n"
            + "\n".join(f"  - {r}" for r in rejections) + "\n\nRevised WorkflowDraft:")
    return [{"type": "text", "text": text}]
