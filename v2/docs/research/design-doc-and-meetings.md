# NetGent V2 — Design Doc and Meeting Record

A single, faithful reference for the V2 design material: the design doc as written (including its
diagrams and its empty sections), and structured accounts of the two available huddle transcripts.
This document **records**; it does not critique. For criticism and recommended edits see
[`design-doc-review.md`](design-doc-review.md); for the current normative reading of the formalism see
[`../OVERVIEW.md`](../OVERVIEW.md).

## 0. Provenance

| Source | What it is | Date |
|---|---|---|
| `/tmp/meetings/design.txt` | "NetGent V2 Design Doc", DOCX→plain-text conversion. 131 lines. Author: Eugene Vuong, with a section attributed to Manni Moghimi | undated |
| `/tmp/meetings/media/image1–6.png` | The doc's six extracted figures (Excalidraw diagrams, one YAML screenshot, one whiteboard photo) | — |
| `/tmp/meetings/meeting1.txt` | Huddle transcript, Eugene ↔ Manni, ~39 min (last stamp 38:36) | **no date header** |
| `/tmp/meetings/meeting3.txt` | Huddle transcript, Eugene ↔ Manni, ~46 min | **Aug 5, 4:06–4:52 PM ET** (per its header) |

**Meeting 2 is not available.** [`meetings-summary.md`](meetings-summary.md) summarizes a ~60-minute
Meeting 2 (error taxonomy, expiry/decay, validation agent, circular transitions, metrics), so the
recording existed at some point; it is not in this source set and nothing here re-verifies it.
Anything below marked *(M2, second-hand)* comes from that earlier summary only.

**Chronology wrinkle.** Meeting 1 carries no date header. In Meeting 3 at [44:47] Manni apologizes
for having "tripped up like on the state and transitions **today**" — the event that occurs at
Meeting 1 [25:00]. Both meetings also refer back to a discussion "yesterday." So Meetings 1 and 3
plausibly share Aug 5, with Meeting 2 adjacent. Ordering 1→2→3 is content-consistent; calendar order
is not established.

**Earlier, shallower passes** (not duplicated here): `meetings-summary.md` (all three meetings,
narrative) and `design-doc-review.md` (a critique of the 10-page **PDF** export). Two artifact
differences are worth flagging: the PDF review reports a `Grammar: TODO!` line and a red-highlighted
"Agent Side" block; **neither survives the DOCX→text conversion** used here (no `TODO` string in
`design.txt`, no color information). The PDF had 7 images to this conversion's 6 — the review notes
one whiteboard photo is a crop of the other, which would explain the difference.

**Transcription caveats.** Both transcripts are auto-generated with heavy crosstalk. Recurring
artifacts, flagged rather than silently corrected: *stay / stage / date / say / said* → **state**;
*transaction* → **transition**; *notes* → **nodes**; *FPC / PS / eps* → **epsilon (ε)**;
*Pomana / Pomona / Parmata* → **Pramana**; *scala draw / Excalibur / calendar* → **Excalidraw**;
*grounder / grabbit / drama* → **grammar**; *E one / L / LM* → **LLM**; *NSA* → **NFA**;
*set of clothes* → **set of flows**; *ARPIT* → **Arpit**. Where a line's meaning turns on such a
word, the ambiguity is called out inline.

---

## 1. The design doc, as written

### 1.1 Goal

> "NetGent is an autonomous AI agent engineered to generate reproducible scripts for complex network
> tasks across diverse environments, including web browsers and terminal shells. Our objective is to
> provide a workflow that offers the flexibility of parameter customization while maintaining
> rigorous task-specific constraints through a deterministic, no-code configuration framework."

### 1.2 The agent contract: prompt + input schema + output schema

The user supplies a natural-language prompt plus schemas:

```
prompt: "your NL prompt"
input schema:  { x: "your NL description", a: "your NL description" }
output schema: { c: "your NL description" }
```

Worked example:

```
Prompt: "Create the Zoom meeting under the name {{ user_name }}"
input schema:  { user_name: name of the user }
output schema: { zoom_code: zoom code }
```

The input schema tells the agent **which parts of the config are dynamic**. The doc states the
`{{ }}` double-curly-bracket grammar as intent, not as built: *"We will plan to implement double
curly bracket as a grammar to make our AI Agent understand that this is a parameter for the
argument."* Output exists so a result can be consumed downstream — *"to pass into another NetGent
workflow input for our Pramana."*

### 1.3 The four agents

**Figure — `image1.png`** (belongs to the Agent section, p. 1). A clean Excalidraw block diagram:
`Prompt` → **Planner Agent** → **Interaction Script Generator** → **Validation Agent** → `Workflow`.
Planner "Delegates Agents" downward to **Discovery Agent(s)**, whose output loops back up into the
Planner. Two repair edges: `Missing Gaps?` from the Interaction Script Generator back to the Planner,
and `Script Failed?` from the Validation Agent back to the Generator. Note the diagram says
*Interaction Script Generator* where the prose says *Workflow Generator Agent*, and that the picture
**terminates at `Workflow`** — no replay, no runtime, no breakage detection.

- **Planner Agent** — "identify the most reliable methodology for task completion." Generates
  "self-evolving plans or hypotheses," orchestrates a *fleet* of Discovery Agents on specific
  explorations and configuration tests, and "continuously analyz[es] the feedback loop of successes
  and failures" to adjust strategy.
- **Discovery Agent** — determines the most effective way to interact with a site, guided by the
  Planner. It captures four diagnostic artifacts, enumerated explicitly:
  - **Action Logs** — detailed event sequences for each interaction step;
  - **Web Artifacts** — saved HTML page states, for visual and structural analysis;
  - **Network Capture** — `.har` files, full network traffic history;
  - **Summary of Actions** — what the agent ran to reach the task, and whether it failed or succeeded.

  It is equipped with browser automation **and HTTP CLI capabilities**, and "systematically navigates
  complex front-ends to isolate and identify all the particular states."
- **Workflow Generator Agent** — produces the replayable config from the prompt plus the best
  methodology. Its output goes to Validation. **Fallback rule:** "If the Workflow Generator Agent is
  missing a gap within its workflow, it will fall back to the Planner Agent to find the answer to the
  question."
- **Validation Agent** — ensures the "dynamic" nature of the workflow by generating **multiple test
  cases** it must pass: different video, different pop-up, different parameter values. The doc places
  the repair loop here: "This is where the true refining and fixing step actually happens between the
  Validation Agent and the Workflow Generation Agent."

### 1.4 Eugene's workflow definition (NFA System)

- **State**: "Consists of a sequence of atomic actions (e.g., typing, clicking). Additionally, each
  state defines a set of transitions to subsequent states. Upon completing these actions, the system
  evaluates defined triggers or conditions to determine the appropriate next state."
- **Transition**: "the bridge between states. It specifies the logical conditions or triggers that
  dictate when the workflow proceeds from the current state to the next."
- **`on` handler**: "a system that checks between every step/atomic action of the workflow to handle
  unexpected pop-ups or interrupts. `on` handler can be local to the state or global to the workflow
  (running for all states)." Motivation: "Standard state machines assume a predictable flow, but
  websites frequently inject unsolicited elements, such as promotional pop-ups, cookie consent
  banners, or unexpected CAPTCHAs, that appear non-deterministically. Without a dedicated
  global/local `on` handler, these interruptions would force the workflow into an error state."

**"Can't we implement another state?" — the N×M argument.** "If you have N steps and M potential
pop-ups, you would need to define M transitions for every one of those N steps to handle the
interruptions, resulting in a fragile, unmaintainable web of state transitions. A global `on` handler
separates your main task from the clutter of the website."

The YouTube example: navigate to YouTube → search for the video → select it from the list → watch for
the desired duration. Then: "there could be a random pop-up that happens during the steps," and the
two treatments are contrasted — pop-up-as-state "would mean that we have to break up our atomic steps
into smaller, fragmented actions to check for pop-ups constantly, creating an unmanageable explosion
of transitions"; the on-handler "keep[s] our core workflow linear and clean; the handler runs
independently... leaving the main task logic undisturbed."

**Figure — `image4.png`** (the idealized linear flow). Five circles, dark theme:
`Start State: Navigate to "youtube.com"` → `YouTube Homepage: Click on "Search Bar" / Type on "Search
Bar"` → (*If on Video List*) `Video List: Click on "Video"` → (*If on video*) `Video: Fast Forward
Video`; a second edge (*If on No Video Avaliable*) drops to a sink `No Video Avaliable` [sic].
Note the homepage state holds **two** actions — Eugene's "sequence of atomic actions."

**Figure — `image3.png`** (the "Pop Up as New State" hairball). The same chain, but the homepage is
now **split into two single-action states** joined by an *If on YouTube Homepage* edge, and every
state has a paired edge to and from a single `Pop Up: Close "Pop-up"` node — outbound edges labelled
*If on Pop Up*, return edges *If on YouTube Homepage* etc. The visual density is the argument.

**Figure — `image2.png`** (the on-handler alternative). The clean four-state chain again, with a
detached rounded box floating above it: `On Handler: If Pop-up: Close "Pop-up"`. The contrast between
`image2` and `image3` is the doc's central piece of visual argumentation.

### 1.5 Manni's workflow definition (NFA System)

Two sentences plus a definition, verbatim:

- **State**: "an element condition that you can anchor on. (example: anchor for `start_page` state
  below will be smth like 'have text bar which says YT & a search bar next to it & a login button')"
- **Transition**: "a single atomic operation that you can do and move to the next state."
- **Word**: "the sequence of transitions that you need to take to get to the last state (example:
  `["type in YT URL to URL bar", eps, "click on [x]", "type X in search bar and hit enter", "click on
  Xth video", "fast forward X", "wait X", "fast forward Y"]`)"

The `eps` in that example is an ε-transition — so the written Word already encodes the Meeting-3
pop-up model (ε into a pop-up state, then "click on [x]" to dismiss it).

**Figure — `image6.png`** (whiteboard photo, belongs to this section). A photograph of the lab
whiteboard. Legible contents:

- **Task** (black, left): `log into YT (user, pass)` / `Search for "bad bunny"` / `click on first
  video` / `watch for 30 (s)` / `f.f. for 15 (s)` / `watch for 30 (s)`.
- **The NFA** (centre): `N/A` --*I: type in YT_url to URL_BAR*--> `start page`; `start page`
  --*II: Type (X) in search bar AND click enter*--> `video list`; `start page` --*III: Click on
  [hand icon] (login)*--> `login page`; `login page` --*IV: type in X and Y to textbox and click
  Enter*--> back to `start page`; `video list` --*V: Click on (X) video*--> `watch video page`, which
  carries two self-loops: *VI: wait(X)* and *VII: ff(X)*. An unattached bubble reads `login + popup`.
- **The "word" in Roman numerals** — two of them. Lower-left: `(I, II, V, VI, VII)` — the no-login
  path. Upper-middle, under the heading **Analytics**: `{I, III, IV, II, V, VI, VII, VI}` — the login
  path, whose tail `V, VI, VII, VI` matches the task's *watch 30 → ff 15 → watch 30*. This is the
  representation Manni means by "word": **indices into named edges**, not natural-language strings.
- **Atomic OPS** (lower left): `[ wait_for(x: time), click(x: elem), type(x: what, y: where) ]` —
  though the graph also uses `ff(X)`.
- **Red annotations** (undocumented in prose anywhere): `① High Level →`, `Abs NFA ↳ bad bunny watch
  30`, `Conc NFA`, `trigger / Action`, `Timer`. The abstract-vs-concrete NFA distinction appears only
  here.

### 1.6 Demo / Workflow Grammar / BQT++

"'BQT Workflow Grammar' refers to the structured logic and rules that govern how BQT executes
automated browser tasks. This is what the LLM/Agent will be producing to create a
reproducible/**healable** webscraper config **for each ISP**. We propose the following alternative
implementations for this grammar:" — followed by exactly one: **YAML-Based Approach**. ("BQT" is
never expanded.)

- **Benefits**: "Highly readable, easily versioned, and simple to validate against a schema. It
  separates the 'what' (selectors, targets) from the 'how' (execution engine), making it easier for
  agents to generate and repair configurations."
- **Pros** — *LLM Compatibility*: "the schema constrains the output to valid syntax, minimizing
  runtime crashes during AI-driven updates"; *Version Control Efficiency*: "YAML diffs are clean and
  human-readable... seamless rollbacks without needing to recompile"; *Standardization*: "Enforces a
  consistent structure across all ISP scrapers."
- **Cons** — *Logic Limitations*: "Declarative schemas can become overly verbose or impossible to
  implement when facing complex, recursive, or non-linear scraping flows that require custom state
  management"; *Constraint Rigidity*: "implementing a novel browser interaction usually requires
  updating the core framework rather than just the workflow file."

**Figure — `image5.png`** (the only concrete artifact in the doc). A syntax-highlighted screenshot of
a Verizon Fios availability-checker config: `isp: verizon`, `schema: 2`, `version: '1.0'`, then
`states: [search, plans]`. Each state has `steps:` (`goto`, `expect`, `fill`, `press`, `click`, `end`)
where every step carries a natural-language `description`, and a `next:` block of `when:`/`goto:`
edges (`"Good news, Fios Home Internet is available"` → `plans`; `"Be among the first to know"` →
`end: NO_SERVICE`). Parameterization appears as `with: "{{ address.line1 }}"`. A top-level `on:` block
— annotated *"checked between every step"* — declines a phone-plan upsell modal with `max: 3`, and
maps `{ css: "iframe[src*=captcha]" }` to `end: CAPTCHA`. Inline annotations mark `expect` as
*"auto-wait, replaces a blind sleep"* and `goto: plans` as *"the edge."* This YAML encodes **Eugene's**
model: steps inside states, conditions on edges.

### 1.7 Better than the Baseline (NetGent V1)?

Three sub-headings, one sentence of content:

- **Validation Loop**: "Self-explanatory. Originally, NetGent does not have any validaiton loop" [sic].
- **Better Grammar**: *(empty)*
- **Dynamism**: *(empty)*

### 1.8 Different from Pramana

"Pramana is a workflow DAG engine and orchestration system that can run multiple NetGent workflow in
parallel, sequencely or both. It also supports context passing so you are able to pass output to
input, etc. Pramana also support the YAML based system as well. On the other hand, NetGent allows
creating workflow on a per application use case like Zoom, Shell Commands, etc."

### 1.9 Workflow Breakage Detection

**Website side.**

- **UI Drift** — "structural or visual changes within a specific page or interaction element that do
  not necessarily change the logical path but break the ability to interact with that element."
  Examples: CSS selector changes, `data-testid` updates, minor layout shifts.
- **Flow Drift** — "changes in the overall sequence or logic of an application's interaction model,
  where new screens, steps, or conditional branching logic are introduced into the established path."
  Examples: an added "Enter PIN" modal between existing steps; a "Profile Selection" now required
  before the dashboard.
- **Website Jitter** — given only as "Handling Rare Events: Jitter often manifests as rare obstacles
  (e.g., promotional pop-ups, slow-loading spinners) that may only occur in 5% of runs," followed by
  a **dangling empty bullet**.

**Agent side.** (In the PDF this whole block is highlighted red — a Meeting-2 marking that did not
survive conversion.)

- **State Dedupping** — heading only, no body.
- **Circular Transitions** — one bullet: "We have an NFA for each platform. The Planner agent will
  output a sequence of transitions that you will take to get to your objective." (This is the word /
  control sequence doing load-bearing work: a finite emitted sequence makes cycles a non-issue.)

### 1.10 Empty or TBD sections

`Better Grammar` · `Dynamism` · `Website Jitter` (dangling bullet) · `State Dedupping` ·
`Validation/Error Fixing` (heading, no body) · `Metrics/Evaluation` (heading, no body — the document
ends there) · "alternative implementations" plural with one alternative given · the `{{ }}` grammar
described as planned, not built. In the PDF version, additionally `Grammar: TODO!`.

---

## 2. Meeting 1 — the on-handler debate, and the inverted definitions

**Positions entering.** Eugene has written the design doc's definitions and wants the `on` handler
adopted. Manni has a whiteboard NFA and is skeptical that "pop-up" is a definable category. They
believe, for the first 25 minutes, that they share one model.

**Manni opens in favour, with a caveat** [0:46]: interruptions "are still states, but I agree that we
should differentiate them from the main states... they're gonna clutter up the NFA like crazy." He
immediately narrows it: "we probably don't want to treat all the pop-ups as one." His question, asked
at [1:20] and never fully answered: *"how does the system distinguish a normal state from the state of
an on trigger?"*

**Eugene's classification story** [1:39]–[4:46]: it happens at workflow-generation and validation
time. "If it looks like a pop-up in terms of the vision side, then it would classify as a pop-up, so
it would be on as an on handler" [1:55]; plus empirical evidence from testing "on multiple types of
inputs." Scope is broader than pop-ups — "ads, cookies" [2:34] — and Eugene defines it functionally:
"it's meant for any type of unexpected interruption within the flow" [2:49]; "a pop-up would be
something that's not within the flow of its task" [3:55], appearing "at a different part of the
application, during different steps, or during the same state" [4:10].

**Manni's core objection** [5:02]–[5:34], the strongest argument he makes all meeting: "I don't feel
like I would be able to classify what a pop-up is... it's not a well-defined thing, and the hardest
part is that... the first time that you're going to see it, it's really going to be hard for the
system to distinguish between a real state and a pop-up." Recognition requires repeated observation:
"once you see it a couple of times and see that it's connecting to different [states]."

**Manni's balance sheet** [5:59]–[6:53]. Pro: doesn't clutter the NFA. Pro: "it's making the grammar
much more understandable... if we have a complex NFA, the grammar could get out of hand." Con: "we're
adding another layer of complexity on top, and we're relying on an agent to do it, **which Arpit is
going to push back against**." And: "I don't know if an agent can do it consistently because I don't
know if I could do this consistently."

**Eugene's framing** [6:59]: "an NFA is meant to be predictable, but... we're using an NFA for an
unpredictable moment — that's the point of the on handler."

**The false consensus** [7:33]–[8:36]. Eugene reads his written definitions aloud and asks for
agreement twice. Manni: "this is like exactly what I had in mind"; "it's good that we have consensus."

**Turning point 1 — one atomic action per state** [8:38]–[11:08]. Eugene derives it from the agreed
definition: if triggers are evaluated after a state's actions complete, and a pop-up can fire at any
moment, then "we have to make every single state with one atomic action" — otherwise there is no
check point between two actions. He points at the pop-up diagram: "click on search bar, and then if
on YouTube home page, click on type on search bar — those are 2 states now" [10:39]. Manni gets it at
[10:56]: *"Oh, you're making each state 1 atomic operation, not a couple."* And concedes: "having 1
per state actually makes sense... it adds more states, but you would need to recreate less states if
you need to do something different." At [17:01] he restates the concession explicitly — "that's
better than what I had in mind."

**The cost debate** [12:27]–[14:06]. Manni: the con is a larger graph and more conditions to check;
"in order to remove that redundancy we're adding a complex step to the process, and we're making it
more undeterministic." His red line, stated precisely [13:26]: "if the graphs are going to be large,
that's fine, but if you have a condition that's gonna create steps in an uncontrolled manner, that is
when we need to take a step back and redesign." Eugene's counter-risk [18:05]: "the more states, the
more transitions we have, the more things can break." Manni's reply [18:25]: "this is the same
transition connected to every state... if one of these conditions breaks, all of them break."

**Interruptions are recognizable only post-hoc** [14:36]–[15:51]. Manni: the only way anyone — agent
or human — identifies an interruption is structurally: a node "heavily connected to everything else in
the graph" while "the other parts of the graph are all sparse." "You can't know the first time that
you're creating it." Eugene agrees: "we need to create the graph and then decide that then." Manni:
"based on the graph, you could do reduction."

**Anchor-based state identity, first statement** [22:04]. Eugene asks the dedup question: same pop-up
seen on different passes at different points — how does the agent reuse one pop-up state instead of
minting several? Manni: "each state will be tied to a specific element... HTML CSS element... It has
some conditions that if you see this, this and this. Basically has a **hook that it anchors on**, and
for pop-ups it's the same as every state. This is how it tells home page from a pop-up versus the
video list." Applied to repair [23:28]: if the homepage drifts, "it would just create a new state for
home page and everything would go to that, and then that would go to the old video list state."

**Turning point 2 — the inverted definitions** [24:54]–[25:41]. Manni, mid-sentence: *"Now that I look
at it, there's a difference between the state and transition definition that we have. So you're
putting the actions inside of the state, I'm putting it on the transitions. You're putting the
element, the hook, on the transition and the action inside the state. I'm doing the opposite."* And
the line that names it: **"Your states are my transitions, my transitions are your states."** Eugene:
"I thought you told me that we had the same definition." Manni [27:50]: "Yeah, I got tripped up,
sorry." The consensus reached at [8:36] is invalidated in the same call.

**Manni's model, spelled out** [26:08]–[26:54]: start page = "an element that has YouTube at the top
and a search bar next to it"; login page = "a login button and 2 text bars"; video list = "a list of
[videos]" — "the element condition, that is inside of the states for me, and the transitions are the
actions: clicking, typing something in, fast forwarding, waiting." His criticism of Eugene's dual:
"you'd create a different state for fast forwarding and waiting on a video... and these will be
tightly connected together, because you could do all of this on the same page."

**The word appears** [27:07]–[27:46]. Eugene: if actions live on edges, how do you know the order?
Manni: "the agent would give it to you... what I've written with the Roman numerals. You have an NFA
and the agent will give you the word that you want to traverse, and you're doing transitions on it and
seeing if this is part of the language or not."

**Fair statement of the trade** [29:35]–[30:38], made by Manni about Eugene's model: "the good thing
about yours is that you don't need a word to traverse it. You could just check all of the conditions
and see where you're going... That also basically means that you need to check every transition, and
this is why you have this idea of let's make that trigger a thing."

**Healing, first version** [30:38]–[32:56]. Manni: with the word, "if a transition breaks, it could
heal that state... he knows what the path is gonna be." Without it: "it's gonna see that it can't do a
transition there, so it's going to add a new state, and then afterwards it has to find the next
state... you're losing all the transitions in between. You don't have the word." Eugene's partial
answer, foreshadowing Meeting 3: the trigger for the homepage expires, "but not the buttons" [31:45].

**Agreed in Meeting 1**: one atomic action per state; states are identified by an element anchor;
interruption-vs-state classification can only happen after the graph exists; the pop-up representation
question is "an optimization problem" [20:47], not a blocker.
**Deferred**: which formalism wins; on-handler vs pop-up-as-state; dedup.
**Action**: Manni to write his definitions down and redraw the same YouTube example (with pop-ups) so
Eugene can read rather than hear it — the meeting ends with him drawing on the whiteboard [33:09]–[38:36].

---

## 3. Meeting 3 (Aug 5) — Manni's formalism, healing, and discovery-in-execution

### 3.1 The model walkthrough

Manni traces both variants of the YouTube flow [0:47]–[1:47]. Without a pop-up: start state → type the
URL into the URL bar → `start page` → type in the search bar and hit enter → `video list` → click a
video → `watch page` → fast-forward or wait. With a pop-up, after reaching `start page`: *"here a
pop-up will happen. The transition that I left for here is an **empty transition** because it
interrupts you — you don't commit any actions."* Then clicking the X is an ordinary transition back to
`start page`.

Vocabulary is fixed in three exchanges: **"by state I mean circle, by transition I mean edge"** [3:31];
ε is *"empty stream, a transition that is forced — it happens to you, you don't do anything to get to
that state"* [4:50], which Eugene glosses correctly as "no input consumed" [7:25]; and the state still
changes on an ε-edge because *"the anchor that you have changes"* [7:15]. Each pop-up type gets its own
state — "you click on X... or if it's a cookie pop-up, you click on decline. It depends on the pop-up.
You have different states for different pop-ups" [6:13].

**The word is renamed** [2:47]: *"Word is probably a bad name for this, but this would be called a
**control**."* Definition [3:12]: "the sequence of transitions that you need to take to get to the
last [state]." It is emitted per run and varies with what happens — "it's creating the word as it's
going" [2:07]. Manni's one-line contrast with Eugene's model [3:03]: "yours is like you check
condition and one of them clicks, and that's where you go."

**Single atomic action per transition, re-decided** [8:51]: "we could have a set or a single atomic
action — I think single is better, because if you combine a set of actions... the transition is going
to break more easily." He floats sets once more at [21:39] and retracts twice, for two independent
reasons: Eugene's [21:43]–[21:52] — "what if a pop-up happens during the set? That's the point of the on
handler, it could happen within that set of actions and it's supposed to catch it" — and his own
[22:01] — a set "hides a state change in the middle of the operations, and that state could then have
an action that will take the graph an entirely different way." Accepted cost, stated as the general
rule [22:27]: **"larger graph isn't our problem. Creation of a lot of states because of one bad
decision, that's the problem."**

### 3.2 The healing argument

Eugene sets the criterion [10:45]: "how you even debate this — what would it do if I had to repair it,
and also if I had to build it from scratch."

Manni's challenge [10:56]–[11:31]: "you gotta think about the healing property... one of your
transitions will break and you would need to create a new state, but then how would you know [what
comes next]? Each of my states have a condition, and I could just look up for that condition. How do
you make sure you just change **one** state when one thing breaks?"

**The test case** [13:19]: YouTube renames the search-bar element, so the guard identifying the
homepage breaks.

- *Eugene's model.* The **state** breaks. Eugene [14:34]: "you would have to recreate the whole state,
  until the next one." Manni notes the consequences [14:39]–[15:21]: the stale state is fine because
  "we'll set expiry on the states, so the old broken one would eventually be deleted," but "when you
  create a new state you would need to recreate all of the transitions as well... how do you know your
  next step is going to be go to YouTube homepage, type on search bar? Why would you not create a new
  state for it?" Eugene's answer [15:21]: hand the LLM the goal plus the actions already run and ask
  "what do you think is the next set of actions?"
- *Manni's model.* The **transition** breaks. **"My states don't break, my transitions break"**
  [16:31]. Because an edge has two known endpoints [17:28]: "I know the start of this transition is the
  `start page` state, and the end of it is `video list`, so I just need to re-figure out the
  transition" — plus, if needed, the next state's hook. "I know what state should come after this
  because my transitions are breaking instead of my states, but you don't know what state will come
  after. You need to feed everything into the LLM... unless you have a huge graph, which then will
  mess up your [context]" [18:17].

Manni concedes Eugene's LLM fallback is "actually super fair, and we could do the same thing to mine"
[15:49], and Eugene extracts the concession that an LLM is needed either way [16:50]; Manni's reply is
that his version can be done "a little bit cleaner without AI" [16:16]. **No formal winner is
declared** — Manni himself says "I could be wrong though, so I feel like we need to focus on this"
[19:14] — but the asymmetry is not contested.

**Flow drift, Eugene's counter-example** [22:39]: "what if the set of actions to get from point A to
point B changes?" Manni's dispatch rule [23:41] is the clearest statement of the taxonomy-to-response
mapping anywhere in the record: *"It knows the transition. If it doesn't have the transition at all,
it's going to create a new state — and that's going to happen with flow drift. But if it has the
transition and the only problem is the transition is not working, that's when it knows the end state
of that transition, and we'll fix the transition and the condition of the next state."* Superseded
states and edges are handled by **expiry** [23:32]: "they would have expiration and they'll eventually
be [removed]."

### 3.3 Discovery embedded in execution

Manni raises it as philosophy [25:49]: *"Arpit was like, we should separate bootstrapping from
execution, and he wants to do that with every project. But in this project, I feel like the healing
process should be part of the running process."* Restated as the rule [28:29]: **"Discovery should be
embedded inside of execution when an execution fails."**

The mechanism [27:08]–[29:48]: on a failed transition, don't fire off an external agent that re-derives
the site from scratch — "it should just go into discovery mode and do a couple of discovery checks and
fix it there." Concretely: the X became a red "No" button, so "the transition would change from click
on X to click on red no button, and it'll also check the elements of the next state to see if something
has changed there." Eugene's framing, accepted: "it'll branch off from the session and then see what
the path is and then come back to it" [28:06].

**Where the LLM enters** [30:11], and this is the zero-LLM-replay statement in the record: *"up until
now, we previously had the word, we had the transitions, we had the state — the LLM was not involved in
executing this. It would just fill in the parameters. But now it needs to bring the LLM, the Discovery
thing, back into the loop."*

**Reconnection by anchor matching** [35:00]–[36:53]. Eugene's worry [35:31]: "from this point forward we
are going to always be creating new states then, because I guess we cannot reconnect to the old
states." Manni: you can — "each state in mine has a hook on it, which is the element, so you could check
every element for that state and see if it's actually matching," optionally augmented with "text
description of what it's gonna look like." Worked example: discovery clicks the green OK instead of the
X, a second cookie dialog appears (a genuinely new state, "pop-up 2"), and clicking OK there returns to
`start page` — "it'll know this is the start page again, because it could match all of the conditions
for any other state that you have." Transition *selection* uses the same trick [24:51]: match a
natural-language description of the intended action against the state's outgoing transitions —
"our transitions are atomic, so if it needs to type in something and the only transition that state is
offering is clicking on something, it'll know that it's not the same thing." Manni labels the whole
strategy the simplest option available [34:23]: "that is the simplest thing we could do; we could
definitely do better."

Eugene's unresolved objection is backtracking [30:44]–[33:38]: if the branch discovery takes is *wrong*
— "there's N buttons that can result in different pages" — how does it recall and try another? "Do we
have to do multiple passes to try all the combinations of the word?" Manni's answer is the divergence
heuristic ("it'll try a couple of different paths... find one that doesn't diverge, discard the
others") and, otherwise, "that depends on discovery."

### 3.4 "States become triggers" — the on-handler dissolves

Eugene asks directly [37:26]: "do you agree we should have an on-handler for the system or not?"
Manni's answer [37:33]–[38:40] converts rather than rejects: "we're drawing the NFA right now, but this
NFA needs to be translated to a grammar, and I'm thinking the grammar will have an on handler — and the
on handler will basically be the element that I'm matching to." The rendering: *"On `N/A`, you could do
transition 1 and go to state blah blah, you could do transition 2 and go to state blah blah. On `start
page`, you can do transition — click on the login thing — and go to `login page`."* Then the sentence
that closes the argument that opened Meeting 1: **"the states will be the triggers and the transitions
will be the transitions."** Eugene accepts and asks him to write it into the spec.

### 3.5 Closing worries

Process, unresolved. Eugene [19:44]: "I think we should just try implementing a simple prototype and
seeing if it is able to handle some kind of randomness." Manni [19:57]: "we can implement it, but I feel
like we should figure this out first and then implement." Manni's discomfort with their own sequencing
[42:11]–[43:30]: "this is a complicated problem. I don't know how we wanted to get into implementation
before we even... we're **discovering issues that we didn't know about yesterday, right now**." And:
"we're too deep now into design, which is not that good either, because if we didn't account for
something here and it's a breaking thing, we're cooked." Eugene's compromise [42:49]: "you just have to
prototype at a smaller scale... and verify if it works, but don't implement the whole thing" — explicitly
not like Pramana, where "I just built everything." Manni [43:43]: "this is a little bit more complicated
than Pramana" [transcript: "Pomana"/"Pomona"] — "it's been a while since I've worked with state machines
for doing agentic whatever we're doing here."

The remaining gap, and the closing bet [20:18]: *"we have the NFA figured out, we have the definition of
states and transitions figured out. The only thing that's gonna be left is what the discovery process is
going to look like, and I feel like somebody's definitely solved that already... we just need to find the
right paper for that and then we'll be chilling."*

Finally, the working norm both restate [44:33]: put it in writing. Eugene: "if I explained it to you, you
would probably agree with me, but if you actually read this, then I can see it properly."

---

## 4. Decisions log

Status is as of the two available transcripts plus the design doc; "code" cites the current `v2/` tree.

| # | Decision | Proposed by | Where | Status | In code |
|---|---|---|---|---|---|
| 1 | Model each site as an NFA | both | doc; M1 | agreed | `schema/workflow.py` (`Workflow`, `State`, `Transition`) |
| 2 | Exactly one atomic action per unit (per *state* in Eugene's model; per *transition* in Manni's) | Eugene derived it; Manni conceded | M1 [10:56], [17:01]; re-decided M3 [8:51] | **agreed** | `Transition.action: Action` — one, discriminated |
| 3 | States carry an element **anchor/hook** condition; transitions carry the action | Manni | M1 [22:04], [25:00]; M3 [0:47] | **agreed** (Manni's model normative per `OVERVIEW.md` §2) | `State.conditions: list[Trigger]` (`url_matches`, `selector_visible`, `selector_hidden`, `title_contains`) |
| 4 | Interruptions are **ε-transitions** into per-pop-up states; dismissal is an ordinary edge back | Manni | M3 [1:28], [4:50], [6:13] | **agreed** | `NoopAction` — docstring: "The ε-transition action" |
| 5 | "Word" renamed **control / control sequence** | Manni | M3 [2:47] | agreed | `Workflow.control` / `control_sequence`; `EdgeStep` |
| 6 | Control is a bounded regular expression (`Branch`, `Repeat`), not a flat word | *post-dates these sources* | — | implemented | `schema/control.py`; `Repeat.max_iterations` mandatory |
| 7 | Global/local `on` handler as its own construct | Eugene | doc §on handler; M1 throughout | **dissolved** into "states become triggers" M3 [38:40] | no `on:` construct; interrupts = ε-edges + `Branch` arms |
| 8 | Pop-up-as-state rejected via the N×M argument | Eugene | doc | **reversed** by M3 | — |
| 9 | Interruption-vs-real-state is only decidable post-hoc, from graph density | Manni | M1 [15:08] | agreed | not implemented |
| 10 | Repair heuristic: recreate only the drifted state, re-point to existing downstream states | Manni | M1 [23:28] | agreed | not implemented |
| 11 | Healing localizes to a **transition** (both endpoints known) rather than a state | Manni | M3 [16:31], [17:28] | agreed in substance; no formal winner declared | not implemented |
| 12 | Dispatch rule: no matching transition ⇒ flow drift ⇒ new state; matching transition that fails ⇒ UI drift ⇒ fix edge + next state's hook | Manni | M3 [23:41] | agreed | not implemented |
| 13 | **Expiry** on stale states/transitions | Manni | M1 [31:28]; M3 [14:39], [23:32] | agreed | not implemented (no expiry field) |
| 14 | Healing embedded **inside** execution (branch locally, fix, resume) — consciously overrides Arpit's separate-bootstrapping rule | Manni | M3 [25:49], [28:29] | agreed between the two; **not cleared with the PI in these sources** | not implemented |
| 15 | Reconnect by matching candidate pages against all known state hooks + descriptions | Manni | M3 [36:29] | agreed | partial: `State.description`, `Transition.id` exist; no matcher |
| 16 | Transition selection by NL-description matching against outgoing edges | Manni | M3 [24:51] | agreed | `description` fields exist |
| 17 | Zero LLM at replay; the LLM only fills parameters | Manni (stated), doc thesis | M3 [30:11] | **agreed** | enforced — `tests/unit/test_import_boundaries.py`; `executor/`, `browser/` may not import langchain |
| 18 | `{{ }}` parameter grammar over an input/output schema | Eugene | doc | agreed | implemented with different syntax — `Param` + `${name}`, plus dynamic `ParamSource` and a regex `guard` |
| 19 | Four-agent pipeline (Planner / Discovery / Generator / Validation) | Eugene | doc; `image1` | partially built | `agent/explorer`, `generator`, `validator`, `orchestrator.py` — **no Planner package** |
| 20 | Generator falls back to the Planner on gaps; Validation loops back to the Generator | Eugene | doc; `image1` | open | not implemented |
| 21 | Validation Agent generates test cases to prove "dynamism" | Eugene | doc | open | `validator` today is a zero-LLM replay check, not a test-case generator |
| 22 | Discovery captures action logs, HTML, HAR, action summaries | Eugene | doc | agreed | partial — `--trajectory DIR` keeps screenshots + records (`schema/records.py`) |
| 23 | Declarative YAML config; schema-constrained LLM output | Eugene | doc | agreed | YAML and JSON both parse to the same pydantic tree (`workflow.py` docstring) |
| 24 | Breakage taxonomy: UI drift / flow drift / jitter | Eugene | doc | taxonomy agreed; response mapping only stated verbally (row 12) | not in code |
| 25 | Circular transitions are a non-issue because the planner emits a finite word | Eugene | doc (Agent Side bullet) | agreed | analogue: `Repeat.max_iterations` as the red-line backstop |
| 26 | State dedup policy | — | doc heading | **open, empty** | duplicate ids rejected; no semantic dedup |
| 27 | Prototype small-scale now vs. close the design first | Eugene vs Manni | M3 [19:44] vs [19:57] | **unresolved**; in practice Eugene's position prevailed (v2 exists) | — |

---

## 5. Open questions

Each with the strongest form of each side **as stated in the sources**.

1. **Can an agent reliably classify "interruption" vs. "real state"?**
   *Manni:* it is not a well-defined category even for a human; on first sighting a pop-up is
   indistinguishable from a legitimate state, and recognition requires seeing it densely connected
   across a graph you don't have yet [M1 5:02, 15:08]. Relying on an agent for it "adds a layer of
   complexity... which Arpit is going to push back against" [M1 6:17].
   *Eugene:* it is decidable from evidence — vision-side appearance plus repeated runs with varied
   inputs — and definitionally an interruption is "not within the flow of its task" and fires at random
   [M1 1:55, 3:55]. Both later agree the decision can only be made *after* the graph exists [M1 15:45].

2. **On-handler vs. pop-up-as-state.** Formally dissolved at M3 [38:40] — states render as `on`
   trigger clauses — but the doc still argues one side.
   *Eugene:* N steps × M pop-ups yields a "fragile, unmaintainable web," and a handler keeps the main
   flow linear; crucially, only a handler catches a pop-up occurring *inside* a multi-action step [doc;
   M3 21:52].
   *Manni:* it is conceptually still a state; the density in the diagram is a drawing artifact ("this is
   the same transition connected to every state" [M1 18:25]); and you pay the same per-step checks
   either way. The single-atomic-action rule removes Eugene's inside-a-step case entirely.

3. **Which model heals better?** No formal winner.
   *Manni:* "my states don't break, my transitions break" — both endpoints of a broken edge are known,
   so repair is local and needs no whole-graph LLM dump [M3 16:31, 18:17].
   *Eugene:* a broken state is recoverable by giving the LLM the goal plus the actions already run [M3
   15:21] — and Manni's model needs an LLM in that loop regardless [M3 16:50], which Manni concedes
   while claiming his version can be done "cleaner without AI" [M3 16:16].

4. **Is the word/control necessary?**
   *Manni:* without it, on breakage the executor can't determine the successor and loses intermediate
   transitions [M1 32:37].
   *Manni, arguing the other side fairly:* "the good thing about yours is that you don't need a word to
   traverse it — you could just check all of the conditions and see where you're going" [M1 30:08]. The
   cost of that is checking every transition, which is what motivates the handler in the first place.

5. **How does discovery verify that a branch it took is the right path, and how does it back out?**
   *Eugene:* "there's N buttons that can result in different pages" — do we need multiple passes over
   combinations of the word? [M3 33:44].
   *Manni:* "that depends on discovery"; the simplest strategy is to diverge along a few paths, keep the
   one that reconnects to a known state, discard the rest — "we could definitely do better" [M3 34:23].

6. **What is the discovery algorithm at all?** The doc specifies what discovery *captures*, never how it
   explores, terminates, or budgets. Manni's closing position is a bet: "somebody's definitely solved
   that already, we just need to find the right paper" [M3 20:18]. Nothing in the sources hedges it.

7. **State dedup and expiry policy.** Expiry is agreed in principle three times and never given a rule
   (usage-count-based decay is a *(M2, second-hand)* claim). `State Dedupping` is an empty heading.

8. **Design-first or prototype-first.** *Manni:* "we should figure this out first and then implement" —
   and separately, "we're too deep now into design... if we didn't account for something here and it's a
   breaking thing, we're cooked" [M3 19:57, 43:10]. *Eugene:* prototype at small scale to settle the
   design empirically, without building the whole system [M3 19:44, 42:49].

9. **Does the PI accept healing inside execution?** The override of Arpit's separate-bootstrapping rule
   is decided between the two collaborators [M3 25:49]; no source records his response.

10. **Scope.** The doc simultaneously claims browsers *and terminal shells* (Goal, Pramana section),
    per-ISP scraper configs (grammar section, `isp: verizon`), and Zoom meeting creation (the input-schema
    example). Never reconciled; "BQT" is never expanded.

---

## 6. Quotes worth keeping

1. **Manni [M1 1:20]** — "How does the system distinguish a state, like a normal state, from the state of
   like an on trigger?" *(the question that runs through all three meetings)*
2. **Manni [M1 5:02]** — "I don't feel like I... would be able to classify what a pop-up is... it's not a
   well-defined thing, and the hardest part is that... the first time that you're going to see it, it's
   really going to be hard for the system to distinguish between a real [state] and a pop-up."
3. **Manni [M1 6:17]** — "We're adding another layer of complexity on top, and we're relying on an agent to
   do it, which Arpit is going to push back against."
4. **Eugene [M1 6:59]** — "An NFA is meant to be predictable, but... we're using an NFA for an unpredictable
   moment — that's part of why we have the on handler."
5. **Manni [M1 10:56]** — "Oh, you're making each [state] 1 atomic operation, not a couple." *(the turning
   point on atomicity)*
6. **Manni [M1 13:26]** — "If the graphs are going to be large, that's fine, but if you have a condition
   that's gonna create steps in an uncontrolled manner, that is when we need to take a step back and
   redesign the process."
7. **Manni [M1 22:04]** — "Each state will be tied to a specific element... Basically has a hook that it
   anchors on... This is how it tells home page from a pop-up versus the video list."
8. **Manni [M1 25:00]** — "You're putting the actions inside of the state, I'm putting it on the
   transitions... **Your states are my transitions, my transitions are your states.**"
9. **Manni [M3 2:47]** — "Word is probably a bad name for this, but this would be called a **control**."
10. **Manni [M3 4:50]** — "Epsilon, empty stream — a transition that is forced, like it happens to you, you
    don't do anything to get to that state."
11. **Manni [M3 16:31]** — "**My states don't break, my transitions break.**"
12. **Manni [M3 17:28]** — "I know the start of this transition is the start page state, and the end of it
    is video list... so I just need to re-figure out the transition."
13. **Manni [M3 22:27]** — "Larger graph isn't our problem. Creation of a lot of states because of one bad
    decision — that's the problem."
14. **Manni [M3 25:49]** — "Arpit was like, we should separate bootstrapping from execution... but in this
    project, I feel like the healing process should be part of the running process." → [28:29]
    "**Discovery should be embedded inside of execution when an execution fails.**"
15. **Manni [M3 30:11]** — "Up until now... the LLM was not involved in executing this. It would just fill
    in the parameters." *(the zero-LLM-replay statement)*
16. **Manni [M3 38:40]** — "**The states will be the triggers and the transitions will be the
    transitions.**" *(the on-handler dispute dissolves)*
17. **Manni [M3 42:38]** — "We're discovering issues that we didn't know about yesterday, right now."
18. **Eugene [M3 42:49]** — "You just have to prototype at a smaller scale... and verify if it works, but
    don't implement the whole thing."
