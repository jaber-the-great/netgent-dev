# LangGraph multi-agent structures, and which one fits NetGent's compile pipeline

**Summary (read this, skip the rest if you're busy).**

1. The multi-agent taxonomy you remember from LangGraph (supervisor / swarm / hierarchical / network) **no longer exists in the live docs**: `langchain-ai.github.io/langgraph/concepts/multi_agent/` now 301s to the Graph API page, and the canonical list moved to LangChain at `/oss/python/langchain/multi-agent/` as **Subagents · Handoffs · Skills · Router · Custom workflow**.
2. `langgraph-supervisor` is officially deprecated in favour of "wrap the worker as a `@tool`"; `langgraph-swarm` survives but its idea is now documented natively as **Handoffs**.
3. Every one of those five patterns puts **an LLM in the routing decision**. NetGent's compile order is fixed and known, so four of the five are wrong for us by construction.
4. The pattern NetGent already implements is **Custom workflow** — a hand-built `StateGraph` mixing deterministic and agentic nodes. `orchestrator.py` is textbook-correct and should stay.
5. What LangGraph gives us that we are *not* using: **`Send` fan-out** (the real answer to `--runs N` / `--variation`, which the CLI does not implement yet), **typed `input_schema`/`output_schema`** instead of `Any`, **checkpointer + `thread_id`** for resumable exploration, **`get_state_history` / fork** for replayable compile trajectories, and **`interrupt()`** for approve-before-commit.
6. Deep Agents (`create_deep_agent`, v0.7.9) is a *harness*, not a pattern: planning, virtual filesystem, `task`-tool subagents with isolated context. Its subagents are stateless tool calls chosen by a model — the opposite of what a compiler wants. **Do not adopt it for the orchestrator.** It is a candidate for T3 local re-exploration only, and even then a plain subgraph is cheaper.
7. Concrete asks: type `OrchestrationState`, add `Annotated[list, operator.add]` for fan-in, add an `explore_run` node fed by `Send`, cap it with top-level `max_concurrency` (not `configurable.max_concurrency` — the docs example is wrong, see §5.4), keep `generate`/`validate` as pure nodes with no `llm` in scope.
8. Marked-unverified items are collected in §9. Two of the installed `.claude/skills/` files are stale against current docs (§9.1).

---

## 0. Method, and what "current" means here

Everything below was fetched live on **2026-08-26** from `docs.langchain.com` and `raw.githubusercontent.com`, and cross-checked against **the versions actually installed in `v2/.venv`**: `langgraph 1.2.11`, `langchain 1.3.15`, `langchain-core 1.5.5`, `langgraph-checkpoint 4.2.0`, `langgraph-prebuilt 1.1.0` (`v2/pyproject.toml:32-38`). `deepagents` and `langgraph-checkpoint-sqlite` are **not installed** — verified by import.

Where the docs and the installed source disagree, I say so and cite the source file in `.venv`.

NetGent code read first, as instructed:

| File | What it is |
|---|---|
| `v2/src/netgent/agent/orchestrator.py` | the pipeline `StateGraph`: `explore → generate → validate`, `Command` routing, no checkpointer |
| `v2/src/netgent/agent/explore_agent/graph.py` | the browser agent's own `StateGraph`: `observe → decide → act` |
| `v2/src/netgent/agent/explore_agent/browser_agent.py` | `BrowserAgent.run()` — builds and `ainvoke`s the explore graph per run |
| `v2/src/netgent/agent/explore_agent/sweep.py` | one agent, many forms, deterministic outer loop, page-verified outcomes |
| `v2/src/netgent/agent/workflow_generator_agent/compiler.py` | `compile_trajectory()` — **pure code**, no LLM |
| `v2/src/netgent/agent/validation_agent/validate.py` | `validate_workflow()` — **zero-LLM replay** through `Executor` |
| `v2/src/netgent/agent/llm.py` | the `LLM` protocol seam; `LangChainLLM` imports langchain lazily |
| `v2/src/netgent/cli/generate.py` | the `netgent generate` flags |
| `v2/tests/unit/test_import_boundaries.py` | the rule that makes all of this enforceable |

---

## 1. The taxonomy shift (verify this before citing anything older)

### 1.1 The old page is gone

```
$ curl -sL https://langchain-ai.github.io/langgraph/concepts/multi_agent/
<link rel="canonical" href="https://docs.langchain.com/oss/python/langgraph/graph-api">
<meta http-equiv="refresh" content="0; url=https://docs.langchain.com/oss/python/langgraph/graph-api">
```

That page was the source of the "network / supervisor / supervisor-as-tool / hierarchical / custom" taxonomy. It redirects to the Graph API reference. The LangGraph Python doc index (`https://docs.langchain.com/oss/python/langgraph/llms.txt`, fetched 2026-08-26) contains **no multi-agent page at all** — the closest entries are `use-subgraphs.md`, `graph-api.md`, and `workflows-agents.md`.

### 1.2 The canonical list now lives under LangChain

`https://docs.langchain.com/oss/python/langchain/multi-agent/index.md` — five patterns:

| Pattern | Mechanism (from the doc's own table) |
|---|---|
| **Subagents** | main agent coordinates subagents **as tools**; all routing passes through the main agent |
| **Handoffs** | tool calls update a state variable (`active_agent`) that triggers routing or reconfiguration |
| **Skills** | one agent, specialised prompts/knowledge loaded on demand |
| **Router** | a classification step dispatches to one or more specialised agents; results synthesised |
| **Custom workflow** | bespoke LangGraph flow mixing deterministic and agentic steps; other patterns embed as nodes |

The page opens with a warning worth quoting in full because it is the most useful sentence in the whole corpus for us:

> "not every complex task requires this approach—a single agent with the right (sometimes dynamic) tools and prompt can often achieve similar results."

and names the three legitimate motivations: **context management, distributed development, parallelization**. NetGent's motivation is *parallelization* (N exploration runs) and nothing else. That single observation kills most of the pattern space for us.

### 1.3 What happened to `langgraph-supervisor` and `langgraph-swarm`

Both repos are **live, not archived** (GitHub API, 2026-08-26: `langgraph-supervisor-py` last pushed 2026-07-15, 1,646★; `langgraph-swarm-py` last pushed 2026-07-15, 1,558★). But:

- `langgraph-supervisor-py/README.md`, first paragraph: *"We now recommend using the supervisor pattern directly via tools rather than this library for most use cases."*
- The migration guide `https://docs.langchain.com/oss/python/migrate/langgraph-supervisor.md` is blunter: *"The `langgraph-supervisor` package is no longer actively maintained. Instead use the subagents pattern."* Its mapping table: `create_supervisor` → `create_agent` + `@tool`-wrapped subagents; `create_handoff_tool` → a custom `@tool` that calls `subagent.invoke(...)`; nested supervisors → a subagent-as-tool that calls other subagents.
- `langgraph-swarm-py/README.md` still recommends itself (`create_swarm`, `create_handoff_tool`, `default_active_agent`, memory via `.compile(checkpointer=..., store=...)`). There is **no** `migrate/langgraph-swarm` page (404, verified). Its mechanism — a handoff tool returning `Command(goto=..., graph=Command.PARENT)` — is exactly what the **Handoffs** doc now teaches natively (`langgraph-swarm-py/README.md:164` vs `ma-handoffs.md:217`), so the library is now redundant rather than wrong.
- **Hierarchical teams** and **network**: I could not find either documented as a named architecture anywhere in the current `docs.langchain.com` trees I fetched (`langchain/multi-agent/*`, `langgraph/*`, `deepagents/*`). The word "hierarchical" survives only in `langgraph-supervisor`'s README prose and in the Skills doc's unrelated "hierarchical skills" (nested skill trees). **Treat "hierarchical teams" and "network" as retired terminology.** (unverified: whether an archived copy is still served somewhere)

---

## 2. The primitives the patterns are built from

These are the parts NetGent actually touches. All verified against `langgraph 1.2.11` in `v2/.venv`.

### 2.1 State, schemas, reducers

`StateGraph(state_schema, context_schema=None, *, input_schema=None, output_schema=None)` — verified signature from the installed package. The docs' key points (`graph-api.md` §"Multiple schemas"):

- A node **can write to any channel in the graph state**, not only the ones in its declared input schema. The graph state is the union of every schema referenced.
- `input_schema` / `output_schema` are *filters*: they constrain what a node reads and what `invoke` returns. Declaring a `PrivateState` used only between two nodes keeps it out of the graph's public output.
- **Private channels are not redacted when streaming.** `stream_mode="values"` emits all channels including private ones; pass `output_keys=[...]` to restrict. (`graph-api.md`, the Warning under "Multiple schemas".) This matters for NetGent because a `DomSnapshot` in state would be streamed in full.
- Each key gets its own reducer. No reducer = overwrite. `Annotated[list, operator.add]` = append. Without a reducer, **two nodes writing the same key in one super-step raises `INVALID_CONCURRENT_GRAPH_UPDATE`** (`errors/INVALID_CONCURRENT_GRAPH_UPDATE.md`). This is *the* failure mode of every fan-out pattern.

`explore_agent/graph.py:39` already gets this right — `steps: Annotated[list[AgentStep], operator.add]`.

### 2.2 `Command` — update + route in one return

Four fields: `update`, `goto`, `graph`, `resume` (`graph-api.md` §`Command`). NetGent uses `update` + `goto` in both graphs.

Two documented traps, both of which NetGent currently avoids by accident rather than by design:

- **`Command` only adds *dynamic* edges. Static `add_edge` edges still fire.** If a node returns `Command(goto="c")` *and* you wrote `add_edge("node_a","b")`, **both** run. Use one or the other per node. NetGent uses `Command` exclusively with a single `add_edge(START, ...)` — correct, but fragile to a well-meaning later edit that "adds the missing edges".
- The return annotation `Command[Literal["generate", "__end__"]]` is **load-bearing for rendering**, not decoration. `orchestration_graph_mermaid()` (`orchestrator.py:136-155`) exists precisely because of this and duplicates the topology to get it — see §7.6 for a way to stop duplicating.

### 2.3 `Send` — map-reduce fan-out

```python
from langgraph.types import Send
def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]
graph.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])
```
(`use-graph-api.md` §"Map-Reduce and the send API"; identical shape in `graph-api.md` §`Send`.)

`Send(node, state)` sends a **different, private state object** to each invocation of `node`. The number of branches is unknown at build time. Fan-in is by reducer on the shared key. `add_node(..., defer=True)` delays a node until all pending tasks finish, which matters when branches have different lengths (`use-graph-api.md` §"Defer node execution").

**This is the exact primitive for `--runs N` and `--variation name=value`.** Neither flag exists in `cli/generate.py` today (verified: `grep -n "runs\|variation" src/netgent/cli/generate.py` → no matches) even though `CLAUDE.md` documents them. §7.2 sketches it.

### 2.4 Subgraphs

Two communication modes (`use-subgraphs.md` §"Define subgraph communication"):

| Mode | When | How |
|---|---|---|
| **Add as node** — `builder.add_node("n", compiled_subgraph)` | parent and subgraph **share state keys** | no wrapper; subgraph reads/writes the parent's channels directly |
| **Call inside a node** — `def n(state): return transform(sub.invoke(map(state)))` | **different schemas**, or you need to transform | you own the mapping in both directions |

A subgraph may declare private keys that the parent never sees (`SubgraphState` with `foo` shared, `bar` private — `use-subgraphs.md` full example).

`Command(goto=..., graph=Command.PARENT)` lets a node **inside** a subgraph route to a node in the **closest** parent graph (`graph-api.md` §`graph`). Constraint stated in the same Note: if you update a key shared by both schemas from the child, **the parent must define a reducer for that key**. `Command.PARENT == "__parent__"` — verified from the installed package.

`Command.PARENT` is what the Handoffs pattern is made of (`ma-handoffs.md:188`, `:217`) and what `langgraph-swarm`'s `create_handoff_tool` emits (`swarm-README.md:164`).

**Visibility limitation, directly relevant to us:** `get_state(config, subgraphs=True)` only works when LangGraph can **statically discover** the subgraph — added as a node, or called inside a node function. It does **not** work when a subgraph is invoked from inside a *tool* function, which is exactly how the Subagents pattern works (`use-subgraphs.md` §"View subgraph state", Note; restated at `ma-subagents.md` §"Checkpointing and state inspection"). So the tool-calling subagent pattern trades away state inspection. NetGent invokes its explore graph from a **node** (via `BrowserAgent.run()`), which keeps inspection available — an accidental win worth keeping deliberately.

### 2.5 Tool-calling agents as nodes

The documented "Custom workflow" idiom (`ma-custom-workflow.md` §"Basic implementation") is unglamorous and is what NetGent does:

```python
agent = create_agent(model="openai:gpt-5.5", tools=[...])
def agent_node(state: State) -> dict:
    result = agent.invoke({"messages": [{"role": "user", "content": state["query"]}]})
    return {"answer": result["messages"][-1].content}
```

The doc's own framing: *"Each node in your workflow can be a simple function, an LLM call, or an entire agent with tools."* NetGent's `explore` node is the third kind; `generate` and `validate` are the first kind. That mix is the pattern, not a deviation from it.

---

## 3. The five patterns: state, control, composition, failure modes

### 3.1 Subagents (the artist formerly known as supervisor)

- **State.** Subagents are **stateless**; all conversation memory lives in the main agent. Each `task` call gets a clean context window. Inputs/outputs cross the boundary as tool arguments and tool results — you can widen this by reading `runtime.state[...]` in the wrapper and returning a `Command(update={...})` instead of a string (`ma-subagents.md` §"Subagent inputs" / §"Subagent outputs").
- **Control.** The main agent's LLM picks the subagent and the arguments. Two tool shapes: **tool-per-agent** or a **single dispatch tool** with an enum/`subagent_type` argument.
- **Composition.** Checkpointing defaults to *per-invocation* (fresh each call, interrupts work, safe in parallel). `checkpointer=True` gives multi-turn subagent memory but breaks repeated calls to the *same* subagent in one node (`MULTIPLE_SUBGRAPHS`). Streaming works; state inspection does **not** (§2.4).
- **Cost.** The docs' own measurement: 4 model calls for a one-shot request vs 3 for Handoffs/Skills/Router, and **8 vs 5** across a repeat request, "because subagents are stateless by design". It wins on multi-domain (5 calls / ~9K tokens vs Skills' 3 calls / ~15K) purely through context isolation.
- **Failure modes.** (a) the subagent does its work in tool calls but omits the result from its final message — the supervisor sees nothing (`ma-subagents.md` §"Subagent outputs" calls this "a common failure mode"); (b) a supervisor with too many subagent tools picks badly; (c) no state inspection, so an interrupt inside a subagent is hard to debug.

### 3.2 Handoffs (≈ swarm)

- **State.** A shared `messages` channel plus an `active_agent` marker; state persists across turns, so the last-active agent resumes on the next turn.
- **Control.** A `@tool` returns `Command(goto="sales_agent", update={...}, graph=Command.PARENT)`.
- **Composition.** Needs a checkpointer for the "resume with the last active agent" property (`swarm-README.md` quickstart passes `InMemorySaver`). Interrupts and streaming compose normally.
- **Failure modes**, from the docs' own Warning: **message-history corruption**. You must hand off both the `AIMessage` carrying the tool call *and* a matching `ToolMessage`, or the receiving agent sees an unpaired tool call and misbehaves (`ma-handoffs.md` §"Context engineering"). And passing the whole subagent history bloats context and confuses the receiver. Handoffs are also **sequential by construction** — the multi-domain benchmark has them at 7+ calls / ~14K+ tokens because they cannot parallelise.

### 3.3 Skills

One agent, progressive disclosure of prompt/knowledge. Cheapest on call count (3 / 5) but **token cost accumulates**: once loaded, every later model call re-processes the skill text (~15K tokens in the doc's multi-domain benchmark, the worst of the four). No isolation. Not a multi-agent structure at all, which is the point the docs are making.

### 3.4 Router

- **State.** A classification step writes a route; downstream agents run and a `synthesize` node merges.
- **Control.** `Command(goto=agent)` for one, or `[Send(agent, {...}) for ...]` for parallel fan-out (`ma-router.md` §"Basic implementation" — this is the only pattern page that reaches for `Send`).
- **Composition.** Stateless by default; the doc's recommended way to make it stateful is to **wrap the whole workflow as a tool** on a conversational agent, so the router stays stateless.
- **Failure modes.** Router-level history management is genuinely hard (the doc carries a Warning telling you to prefer Handoffs or Subagents rather than build a stateful router); and misclassification is unrecoverable because the router does not participate in the downstream conversation.

### 3.5 Custom workflow

- **State.** Whatever you declare. Deterministic and agentic nodes read the same channels.
- **Control.** Static edges, conditional edges, `Command`, `Send` — all of it, decided by you at build time.
- **Composition.** Everything composes because it is just the Graph API: `retry_policy`, `cache_policy`, `error_handler`, `defer`, `durability`, `interrupt()`, checkpointers, `Send` (verified in the installed `StateGraph.add_node` / `.compile` / `.ainvoke` signatures).
- **Failure modes.** You own the correctness. The specific ones that bite: forgetting a reducer under fan-out; mixing `Command(goto=...)` with a static edge on the same node; and a state schema of `Any` that silently accepts the wrong thing (NetGent has this — `orchestrator.py:64-68`).

---

## 4. Deep Agents

`deepagents` **0.7.9** (PyPI, 2026-08-26). Not installed in `v2/.venv`. It is a *harness* built on `langchain.agents.create_agent` + the LangGraph runtime, not a competing runtime — `libs/deepagents/deepagents/graph.py:11-16` imports `create_agent`, `AgentMiddleware`, `HumanInTheLoopMiddleware` from langchain directly.

### 4.1 `create_deep_agent`

Verified signature (`libs/deepagents/deepagents/graph.py:268-288`):

```python
def create_deep_agent(
    model=None, tools=None, *, system_prompt=None, middleware=(),
    subagents=None, skills=None, memory=None, permissions=None, backend=None,
    interrupt_on=None, response_format=None, state_schema=None, context_schema=None,
    checkpointer=None, store=None, debug=False, name=None, cache=None,
) -> CompiledStateGraph[...]
```

Built-in tools per the docstring (`graph.py:291-296`): `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` (shell, only if the backend implements `SandboxBackendProtocol`), and `task`.

`DeepAgentState` puts messages on a `DeltaChannel` "to reduce checkpoint growth from O(N²) to O(N)" (`graph.py`, class docstring) — a nice illustration of what a long-running checkpointed agent costs.

### 4.2 SubAgentMiddleware and the `task` tool

Source: `libs/deepagents/deepagents/middleware/subagents.py` (747 lines).

- `SubAgent` is a `TypedDict` (`:38`) with `name`, `description`, `system_prompt` (all required) and optional `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `response_format`, `permissions`. Inheritance from the main agent is **per-field and non-obvious**: `tools`/`model`/`interrupt_on`/`permissions` inherit; `system_prompt`/`middleware`/`skills` do **not** (`da-subagents.md` §"SubAgent (Dictionary-based)" table).
- `CompiledSubAgent` (`:169`) takes `name`, `description`, `runnable` — **any compiled LangGraph graph**, provided it has a `messages` state key. This is the seam through which a raw `StateGraph` becomes a Deep Agents subagent.
- `GENERAL_PURPOSE_SUBAGENT` (`:303`) is auto-added unless you supply your own of that name. Removing `SubAgentMiddleware` via `excluded_middleware` **raises `ValueError`** — the supported way to run without `task` is `GeneralPurposeSubagentProfile(enabled=False)` plus no synchronous subagents (`da-subagents.md` §"Running without subagents").
- The `task` tool (`:544` sync, `:583` async) is a plain function: validate `subagent_type` against the registry → build fresh subagent state → `subagent.invoke(state, {"configurable": {"ls_agent_type": "subagent"}})` → `_return_command_with_state_update(result, tool_call_id)`. That's it. **A Deep Agents subagent is a compiled graph invoked from inside a tool function** — mechanically the same thing as §2.4's "call a subgraph inside a node", except it happens inside a tool, which is why state inspection is lost.
- The tool description the model actually sees (`:287-298`) states the contract plainly: *"Each invocation is stateless: the agent sees only the prompt you give it and returns a single final report."*

### 4.3 TodoList planning

**This changed and the local skill is stale.** `da-overview.md` §"Task planning": *"Starting in v0.7 task planning is opt-in only. In earlier versions, task planning middleware was included by default."* You now pass `middleware=[TodoListMiddleware()]` explicitly, and it comes from `langchain.agents.middleware`, not from `deepagents`. Todos are `{content, status ∈ pending|in_progress|completed}` persisted in agent state.

The installed `.claude/skills/deep-agents-core/SKILL.md` says "TodoListMiddleware — Default enabled" and lists it under "Core middleware removal … always present". That is **wrong against v0.7.9**. See §9.1.

### 4.4 Filesystem / StoreBackend memory

Backends (`da-backends.md` §"Built-in backends"): `StateBackend` (ephemeral, in graph state), `FilesystemBackend` (local disk), `LocalShellBackend`, `StoreBackend` (LangGraph `BaseStore`, cross-thread durable), `ContextHubBackend`, `CompositeBackend` (path-prefix router).

`StoreBackend(namespace=lambda rt: (rt.server_info.user.identity,))` — the namespace factory is `Callable[[Runtime], tuple[str, ...]]` and receives `rt.context` (your context schema), `rt.server_info`, `rt.execution_info` (thread id, run id, checkpoint id). Namespace choice *is* the isolation boundary: per-user, per-assistant, or per-thread (`da-backends.md` §"Namespace factories").

### 4.5 How this differs from raw LangGraph subgraphs

| | Deep Agents subagent | Raw LangGraph subgraph |
|---|---|---|
| Who decides it runs | **the main agent's LLM**, via `task(subagent_type=...)` | **your code**, via an edge or `Command(goto=...)` |
| Input | a natural-language `description` string | a typed state dict you construct |
| Output | one final message (or a `response_format` JSON blob) | the subgraph's output schema |
| Context | fresh window per call, stateless | whatever you map in; can share channels |
| Discoverable by `get_state(subgraphs=True)` | ❌ (invoked inside a tool) | ✅ (added as / called inside a node) |
| Failure surface | model picks wrong subagent, or omits results from its final message | a `KeyError` in your mapping function, at build time or first run |

The one-line difference: **Deep Agents replaces a graph edge with a model decision.** For a compiler, that is a downgrade, not an upgrade.

---

## 5. Persistence for multi-run pipelines

### 5.1 Checkpointers and threads

`.compile(checkpointer=...)` saves a checkpoint at every super-step; `thread_id` in `config["configurable"]` names the sequence (`lg-checkpointers.md` §"Threads", §"Checkpoints"). Libraries: `langgraph-checkpoint` (bundled, gives `InMemorySaver`), `langgraph-checkpoint-sqlite` (`SqliteSaver`/`AsyncSqliteSaver`), `langgraph-checkpoint-postgres` (`PostgresSaver`/`AsyncPostgresSaver`). Only the first is installed here.

### 5.2 Durability modes

`durability="exit" | "async" | "sync"` on any execution method (`lg-checkpointers.md` §"Durability modes"), confirmed present on the installed `CompiledStateGraph.ainvoke`. `"async"` persists while the next step runs — good throughput, small crash window. `"sync"` persists before the next step starts. `"exit"` only at the end.

For NetGent: an exploration step costs an LLM call plus a browser action. Losing one to a crash is expensive, so `"sync"` is the right default if we checkpoint the explore loop at all — but see §7.5 for why we probably should not checkpoint that loop.

### 5.3 Subgraph checkpointer scoping

Three modes on `subgraph.compile(checkpointer=...)` (`use-subgraphs.md` §"Checkpointer reference"):

| | `None` (per-invocation, default) | `True` (per-thread) | `False` (stateless) |
|---|---|---|---|
| Interrupts | ✅ | ✅ | ❌ |
| Multi-turn memory | ❌ | ✅ | ❌ |
| Same subgraph called twice in one node | ✅ | ❌ (`MULTIPLE_SUBGRAPHS`) | ✅ |
| State inspection | current invocation only | ✅ | ❌ |

The parent must itself be compiled with a checkpointer for any of this to do anything.

### 5.4 Time travel

`get_state_history(config)` returns snapshots newest-first; `invoke(None, past.config)` **replays** from a checkpoint; `update_state(past.config, {...})` returns a forked config you then resume from (`use-time-travel.md`).

The Warning on that page is the important part: **replay re-executes nodes, it does not read from cache.** LLM calls, API calls and interrupts fire again. So "replay the compile" means "re-run exploration", not "re-derive the artifact from the recorded trajectory" — unless the fork point is *after* explore, which is precisely the fork NetGent wants (§7.5).

`update_state` **passes updates through reducers**; use `Overwrite(...)` to replace instead of append (`langgraph-persistence` skill; `lg-checkpointers.md` §"Update state").

### 5.5 Store (cross-thread)

`InMemoryStore` / any `BaseStore`; `store.put(namespace_tuple, key, value)`, `.get`, `.search(namespace, filter=...)`, `.delete`; optional semantic search over embedded fields (`lg-stores.md`). In a node you reach it via `runtime.store`, never a module global. Compile with **both** `checkpointer=` and `store=`.

### 5.6 Concurrency cap — a doc bug worth knowing

`use-graph-api.md` §"Set max concurrency" says:

```python
graph.invoke({"value_1": "c"}, {"configurable": {"max_concurrency": 10}})
```

The installed source disagrees. `v2/.venv/.../langgraph/pregel/_executor.py:135`:

```python
if max_concurrency := config.get("max_concurrency"):
    self.semaphore = asyncio.Semaphore(max_concurrency)
```

It reads the **top-level** `RunnableConfig` key (`max_concurrency` is a documented top-level field of `RunnableConfig` — confirmed via `RunnableConfig.__annotations__`), not `configurable["max_concurrency"]`. **Pass it at the top level:** `await graph.ainvoke(state, {"max_concurrency": 2})`. This matters a lot for us: each parallel exploration run opens its own Chrome.

---

## 6. What NetGent has today

```
orchestrator.py            explore_agent/graph.py
  START → explore            START → observe → decide → act ↺
            ↓ Command                    │        ├─ done → END
         generate                        └─ stuck ──────→ END
            ↓ Command
         validate → END
```

Read against the taxonomy: **`orchestrator.py` is the Custom workflow pattern, and `explore_agent/graph.py` is one agentic node inside it.** Not "a supervisor we haven't finished", not "a degenerate swarm" — the pattern the docs recommend for exactly this shape.

What is already right:

- **Deterministic order.** `explore → generate → validate` is a compiler pipeline. No model chooses it. `Command(goto=END)` on failure is a real early-exit, not a model-chosen one.
- **Zero-LLM downstream, structurally.** `compile_trajectory` (`compiler.py:66`) takes `(traj, name, params, version)` — no `llm` parameter exists. `validate_workflow` (`validate.py:29`) takes `(workflow, param_sets, headless)` and drives `Executor`. Neither *can* call a model; `test_import_boundaries.py` guarantees `netgent.executor` never even imports langgraph.
- **Session isolation per stage.** Each of `explore` and `validate` opens its own `BrowserSession` (`orchestrator.py:84`, `validate.py:43`), so exploration state cannot leak into validation. This is the file docstring's stated intent and it holds.
- **Lazy imports.** Both graphs import `langgraph.graph` **inside** the builder function (`orchestrator.py:73`, `explore_agent/graph.py:53`), keeping `netgent[generate]` optional.
- **A correct reducer already.** `steps: Annotated[list[AgentStep], operator.add]`.
- **The sweep is the right instinct, at the wrong altitude.** `sweep_forms` is a deterministic outer loop around one agent with continuous memory, verifying outcomes from the page rather than the agent's self-report (`sweep.py:99-135`). That philosophy — *deterministic orchestration, verified outcomes* — is what the whole orchestrator should say. It is currently written in Python `for`-loops rather than in the graph, which is fine, but it means the sweep gets no checkpointing, no streaming, no fan-out.

What is weak:

1. **`OrchestrationState` is untyped** (`orchestrator.py:64-68`): `trajectory: Any`, `workflow: Any`, `report: Any`. No `input_schema`/`output_schema`. A node returning the wrong shape fails at the *next* node's `state["..."]` access, not at the boundary.
2. **No fan-out.** `--runs N` and `--variation` are in `CLAUDE.md` but not in `cli/generate.py` (verified). One trajectory in, one workflow out. The synthesis step described in `docs/OVERVIEW.md` §3.1 ("Discovery *fleet*") has nowhere to plug in.
3. **No checkpointer anywhere.** A crash during `validate` throws away the whole exploration — the expensive part.
4. **`orchestration_graph_mermaid()` duplicates the topology** (`orchestrator.py:136-155`) with stub nodes, because the real builder needs `req`/`llm`/`listen`. Two definitions of the same graph will drift.
5. **The `listen` callback is not concurrency-safe.** `emit(stage, text)` (`orchestrator.py:76`) writes an unqualified line. Under `Send` fan-out, three exploration runs interleave into one terminal with no run index.
6. **`snapshot: Any  # DomSnapshot`** sits in the explore graph's state (`explore_agent/graph.py:34`). `DomSnapshot` *is* a pydantic model (`browser/dom/models.py`), so it would serialise — but it is a full multi-frame DOM walk with per-element candidate selector lists, checkpointed **once per step**. Attaching a checkpointer to that graph naively is a footgun.

---

## 7. Recommendation

### 7.1 Keep the linear `StateGraph`. Do not adopt supervisor / subagents / handoffs / Deep Agents for the orchestrator.

The argument is one sentence: **all four of those patterns move the routing decision from your code into a model, and NetGent's routing decision is a fixed compiler pipeline whose whole value proposition is that no model is involved after exploration.** Concretely, a subagent-style orchestrator would let the model decide whether to run `validate` — which is exactly the guarantee `netgent generate` exists to provide.

Secondary arguments: subagents cost an extra model call per delegation (the docs' own benchmark: 4 vs 3 one-shot, 8 vs 5 repeat) purely for coordination we do not need; handoffs cannot parallelise; and both require careful message-history surgery (`AIMessage`+`ToolMessage` pairing) for a pipeline that has no conversation.

Deep Agents specifically: it would add `deepagents` + its middleware stack as a dependency, put a `task` tool in front of a decision we already make in code, and lose `get_state(subgraphs=True)` because subagents are invoked inside tools. Its genuinely valuable pieces (isolated context, one-shot report) are things `BrowserAgent.run()` already provides, deterministically.

**Where Deep Agents could earn its place later:** the T3 tier of the repair ladder (`docs/OVERVIEW.md` §4.1) — bounded local re-exploration at a failure point, where the *task* is open-ended, a filesystem scratchpad is genuinely useful, and `interrupt_on` gives you human escalation for free. Even there, a `CompiledSubAgent` wrapping our existing explore graph is the cheap first step. Not now.

### 7.2 Use `Send` for `--runs N` and `--variation` — this is the one real gap

Replace the single `explore` node with a fan-out. Sketch (matches `use-graph-api.md` §"Map-Reduce and the send API"):

```python
# orchestrator.py

class ExploreRun(TypedDict):
    """Private per-branch state. Never merged into the parent as-is."""
    run: int
    task: str
    params: dict[str, str]        # this branch's variation


class OrchestrationState(TypedDict, total=False):
    trajectories: Annotated[list[AgentTrajectory], operator.add]   # <- fan-in
    trajectory: AgentTrajectory | None                             # the chosen one
    workflow: Workflow | None
    report: ValidationReport | None
    error: str


def _plan_runs(req: GenerateRequest) -> list[ExploreRun]:
    """Pure code: the cross product of --runs and --variation. No LLM."""
    variations = req.variations or [req.params]
    return [
        ExploreRun(run=i, task=req.task, params=p)
        for i, p in enumerate(v for v in variations for _ in range(req.runs))
    ]


def build_orchestration_graph(req, llm, listen=None):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, Send

    async def explore_run(state: ExploreRun) -> dict:
        """One exploration. Its own browser session; its own trajectory."""
        emit("explore", f"[run {state['run']}] {state['task']}")
        agent = BrowserAgent(llm, max_steps=req.max_steps,
                             run_dir=_run_dir(req, state["run"]))
        async with BrowserSession(headless=req.headless) as session:
            traj = await agent.run(session, state["task"], req.url)
        return {"trajectories": [traj]}        # reducer appends; no collision

    def fan_out(state: OrchestrationState):
        return [Send("explore_run", r) for r in _plan_runs(req)]

    async def select(state: OrchestrationState) -> Command[Literal["generate", "__end__"]]:
        """Pure code. Pick / merge the trajectories. NO LLM HERE."""
        ok = [t for t in state["trajectories"] if t.success]
        if not ok:
            reasons = "; ".join(t.stopped_reason or "not completed"
                                for t in state["trajectories"])
            return Command(update={"error": f"exploration failed: {reasons}"}, goto=END)
        return Command(update={"trajectory": _choose(ok)}, goto="generate")

    return (
        StateGraph(OrchestrationState)
        .add_node("explore_run", explore_run, input_schema=ExploreRun)
        .add_node("select", select)
        .add_node("generate", generate)
        .add_node("validate", validate)
        .add_conditional_edges(START, fan_out, ["explore_run"])
        .add_edge("explore_run", "select")
        .compile()
    )
```

Four things to get right, each a documented failure mode:

- **`Annotated[list[...], operator.add]` on `trajectories` is mandatory.** Without it, N concurrent `explore_run` nodes writing the same key raise `INVALID_CONCURRENT_GRAPH_UPDATE`.
- **Cap the browsers.** `await graph.ainvoke({}, {"max_concurrency": req.concurrency})` — top level, not under `configurable` (§5.4). Default 2; N headed Chromes will thrash a laptop.
- **`add_edge("explore_run", "select")` is the fan-in.** All `Send` branches converge before `select` runs. If a later design gives branches different lengths, `add_node("select", select, defer=True)` makes the wait explicit.
- **`select` must stay pure code.** It is where the "choose the best trajectory / merge N trajectories into one NFA" logic goes, and it is the single most tempting place in the whole pipeline to sneak an LLM in. Don't. If merging N trajectories into one NFA turns out to need judgement, that judgement belongs in `workflow_generator_agent/` as a documented algorithm (`docs/OVERVIEW.md` §7 lists the Discovery algorithm as still unspecified), not as a model call.

`_choose` starts as "first successful trajectory" and can grow into "the shortest", "the one whose states the others agree with", or an actual multi-trajectory merge — all pure code, all testable without a network.

### 7.3 Keep `explore_agent` as a *called* subgraph, but type the boundary

Do **not** convert `BrowserAgent.run()` into `add_node("explore", compiled_subgraph)`. The explore graph is deliberately rebuilt per run because its nodes close over the live `BrowserSession`, the task, and the agent's cross-run `history` (`explore_agent/graph.py:9-13`, `:56`). That is the "call a subgraph inside a node" mode from §2.4, and it is correct — it also happens to preserve `get_state(subgraphs=True)` discoverability (§2.4 Note), which the tool-calling alternative would destroy.

What to change is the *contract*. `AgentState` currently mixes durable output (`steps`, `success`, `stopped_reason`, `texts_seen`) with loop scratch (`snapshot`, `observation`, `prev_observation`, `no_progress`, `decision`). Split it:

```python
# explore_agent/graph.py

class ExploreInput(TypedDict):
    steps: Annotated[list[AgentStep], operator.add]

class ExploreOutput(TypedDict):
    steps: Annotated[list[AgentStep], operator.add]
    success: bool
    stopped_reason: str
    texts_seen: list[str]

class AgentState(ExploreOutput, total=False):
    # loop scratch — private to this graph, never in the output
    n: int
    snapshot: Any            # DomSnapshot: big, per-step, do not persist
    observation: str
    prev_observation: str | None
    no_progress: int
    decision: Any

    return (
        StateGraph(AgentState, input_schema=ExploreInput, output_schema=ExploreOutput)
        ...
    )
```

`browser_agent.py:119-122` already reads exactly the four `ExploreOutput` keys out of `final`, so this is a no-behaviour-change refactor that makes the boundary checkable. Note the §2.1 caveat: `output_schema` filters `ainvoke`'s return, **not** `stream`; if we ever stream this graph, pass `output_keys=` too or the `DomSnapshot` goes over the wire.

### 7.4 Nodes, not agents — and make that structural

`generate` and `validate` are nodes. Keep them that way, and make it enforceable rather than conventional:

- Neither node body should have `llm` in scope. Today both are closures inside `build_orchestration_graph(req, llm, listen)`, so `llm` *is* reachable — nothing stops a future edit. Lift them to module-level functions taking `(state, req)` and bind with `functools.partial`, so the graph's construction proves the property. Cheap, and it is the kind of thing a reviewer can check in one line.
- Extend `tests/unit/test_import_boundaries.py` with the compile-time counterpart: assert that importing `netgent.agent.workflow_generator_agent` and `netgent.agent.validation_agent` does **not** pull in `langchain`/`langgraph`. The existing test only covers `schema`/`core`/`browser`/`executor`/`report`; these two packages are inside `agent/` yet are supposed to be model-free, which is precisely the boundary most likely to erode.

### 7.5 Persistence: yes at the pipeline level, no inside the explore loop

**Parent graph — checkpoint it.**

```python
graph = builder.compile(checkpointer=checkpointer)     # InMemorySaver by default
final = await graph.ainvoke(
    {}, {"configurable": {"thread_id": run_id}, "max_concurrency": req.concurrency},
    durability="sync",
)
```

with `run_id` a stable id per `netgent generate` invocation (write it next to `--trajectory` output so it can be quoted back). What this buys, in NetGent terms:

- **Resumable `--runs N`.** Runs 1–3 finished, run 4 crashed on a flaky site: resume the thread instead of re-paying for 1–3. This is the single biggest cost win — exploration is where all the tokens go (`evals/matrix.py` prices Haiku runs per step).
- **Replayable compile trajectories.** `get_state_history(config)` gives the checkpoint after `select` and before `generate`. Fork it with `update_state` to re-run `generate` + `validate` under different `--param` values **without re-exploring**. That is a compiler `-O2` rerun, and it is the honest reading of "replayable compile trajectory" — §5.4's Warning means forking *before* `explore` just re-explores.
- **Approve-before-commit.** `interrupt()` in a node between `generate` and `validate` (requires the checkpointer) implements `docs/OVERVIEW.md` §4.2's *"healing runs inside execution; commitment runs outside it"* at compile time: show the human the compiled NFA, resume with `Command(resume=...)` to accept. Optional, behind a flag; the machinery is free once the checkpointer exists.
- Ship `InMemorySaver` (bundled) as the default, and put `SqliteSaver` behind a `--resume` flag with `langgraph-checkpoint-sqlite` added to the `generate` extra. It is **not currently installed** — verified.

**Explore subgraph — do not checkpoint it.** Compile it `checkpointer=False`, or (if we later want `interrupt()` mid-exploration for a human to solve a login) leave it at the `None` default and drop `snapshot` from the checkpointed channels first. A full multi-frame `DomSnapshot` written once per step, times N parallel runs, times 25–60 steps, is a lot of bytes for something we can always re-derive from the page. `browser_agent.py:126` already persists the durable artifact — `trajectory.json` — which is the thing worth keeping.

**Store — later, and compile-time only.** A `BaseStore` namespaced by site (`("netgent", domain)`) is the natural home for cross-run compile knowledge: which cookie-banner selector worked, which date format this validator accepts — the generalisation of `BrowserAgent.history` (`browser_agent.py:69`), which today only spans one process. `docs/OVERVIEW.md` cites V1.5's `evolution.py` cross-run learning module as prior art. Two hard constraints if we do it: it is **compile-time only** (nothing under `executor/` or `browser/` may read it), and it must never influence the artifact except through the trajectory, or replay stops being reproducible — which would attack the product itself.

### 7.6 Two small cleanups the above makes free

- **Delete `orchestration_graph_mermaid()`'s stub graph.** Once `_plan_runs` is a pure function of `req` and the node bodies are module-level, the real builder can be called with a dummy `GenerateRequest` and a `None` LLM purely to render Mermaid. One topology, one definition, no drift.
- **Make `emit` fan-out-aware.** `Listener = Callable[[Stage, str], None]` becomes `Callable[[Stage, int | None, str], None]` (stage, run index, text), so three concurrent explorations are legible in one terminal. If we want it to survive into a UI later, `get_stream_writer()` + `stream_mode="custom"` is the documented route (verified importable from `langgraph.config`) — but the plain callback keeps langgraph out of `cli/`, which is worth more than the streaming polish today.

---

## 8. Pattern comparison, on the axis that matters

| Pattern | Control decided by | Parallel? | State sharing | Fits NetGent? | Why |
|---|---|---|---|---|---|
| **Custom workflow** (`StateGraph`) | your code, at build time | ✅ (`Send`, parallel edges) | explicit channels + reducers | **Yes — this is what we have** | The compile order is fixed and known. Deterministic orchestration is the product claim, not an implementation detail. |
| **`Send` fan-out (map-reduce)** | your code, per item | ✅ (this is its purpose) | private per-branch state → reducer fan-in | **Yes — adopt for `--runs N` / `--variation`** | Exactly the "Discovery fleet" shape in `docs/OVERVIEW.md` §3.1, with a documented failure mode (missing reducer) we already know how to avoid. |
| **Subgraph called inside a node** | your code | ✅ | you map both directions | **Yes — keep; type the boundary** | `BrowserAgent.run()` already does this; needed because nodes close over a live `BrowserSession`. Preserves `get_state(subgraphs=True)`. |
| **Subgraph added as a node** | your code | ✅ | shared channels, no wrapper | **No** | Requires shared keys and a session-free graph. Our explore graph is rebuilt per run around a live session. |
| **`Command(graph=Command.PARENT)`** | a node inside a child | n/a | needs a parent-side reducer on shared keys | **No (today)** | It is the handoff primitive. Our child returns a trajectory; it does not choose the parent's next node. Revisit only if T3 repair re-enters the pipeline mid-run. |
| **Subagents / supervisor** | **an LLM** | ✅ | tool args in, final message out | **No** | Puts a model in charge of whether `validate` runs. +1 model call per delegation for coordination we already have in code. Loses state inspection. |
| **Handoffs / swarm** | **an LLM** | ❌ sequential | shared `messages` + `active_agent` | **No** | Conversational pattern; NetGent has no conversation. Requires `AIMessage`+`ToolMessage` pairing surgery. Worst multi-domain cost in the docs' own benchmark. |
| **Router** | **an LLM** classifier | ✅ (via `Send`) | route key → agents → synthesize | **No — but steal its `Send`** | We have nothing to classify: the pipeline has one path. The `Send` fan-out half is the part worth taking, without the classifier. |
| **Skills** | an LLM, on demand | ⚠️ limited | one shared context | **No** | Context accumulates into every later call (~15K tokens in the docs' benchmark). We need isolation between runs, not accumulation. |
| **Deep Agents** (`create_deep_agent`) | **an LLM**, via `task` | ✅ | fresh window per subagent; FS/Store backends | **No for the orchestrator; maybe for T3 repair** | A harness for open-ended work. Our compile step is closed-ended. Would add a dependency to replace an edge with a model decision. |
| **`langgraph-supervisor`** | an LLM | ✅ | — | **No** | Officially "no longer actively maintained"; migration guide points at Subagents, which we also reject. |
| **`langgraph-swarm`** | an LLM | ❌ | — | **No** | Superseded by the native Handoffs docs; same objection. |

---

## 9. Unverified, stale, and open

### 9.1 Two installed skills disagree with the current docs

- `.claude/skills/deep-agents-core/SKILL.md` states TodoListMiddleware is "Default enabled" and lists it among middleware that cannot be removed. **Current docs (`deepagents` v0.7): task planning is opt-in**, passed as `middleware=[TodoListMiddleware()]` from `langchain.agents.middleware`. Prefer the live docs.
- `.claude/skills/swarm/SKILL.md` is **not** about `langgraph-swarm`. It is a Claude Code skill for fanning work across subagents via a `swarm_task` PTC tool (`compatibility: Requires @langchain/quickjs code interpreter`). Unrelated to LangGraph multi-agent architecture; it is not a source for this document beyond confirming the naming collision.

### 9.2 Not verified

- Whether an archived copy of the retired supervisor/swarm/hierarchical/network taxonomy page is still served anywhere. I confirmed the redirect; I did not hunt for a mirror.
- `langgraph-swarm-py`'s compatibility with `langgraph 1.2.11` / `langchain 1.3.15`. Its README example imports `create_agent` from `langchain.agents` (the v1 path), which is a good sign, but I did not install or run it.
- Deep Agents' async-subagent machinery (`AsyncSubAgent`, Agent Protocol servers, `update_async_task` / `cancel_async_task`) is documented as a **preview feature** and was read from docs only, not exercised.
- `deepagents` behaviour generally: read from GitHub `main` (v0.7.9) and the docs, **not installed or executed** in this repo.
- LangSmith tracing/eval integration for a fan-out pipeline — out of scope here; `docs/research/langchain-evals.md` is the relevant prior document.

### 9.3 Design questions this document does not answer

- **How to merge N trajectories into one NFA.** §7.2 punts to `_choose` = "first successful". Real synthesis (state identification across runs, ε-transitions for pop-ups that appeared in only some runs) is the Discovery algorithm that `docs/OVERVIEW.md` §7 records as unspecified. It is a pure-code problem, and it is the actual research contribution — a graph pattern will not supply it.
- **Whether `--variation` varies parameters, the starting URL, or the environment.** `CLAUDE.md` says `--variation name=value`, which reads like parameters; `docs/OVERVIEW.md` §3.1's validation agent wants "different videos, different pop-ups", which is broader. `ExploreRun` in §7.2 carries a `params` dict and would need widening for the latter.

---

## 10. Sources

Fetched 2026-08-26. All `docs.langchain.com` URLs also serve a `.md` variant (append `.md`), which is what I read.

**LangChain — multi-agent**
- `https://docs.langchain.com/oss/python/langchain/multi-agent/index.md` — the five patterns, the choosing table, the model-call/token benchmarks
- `.../multi-agent/subagents.md` — supervisor-as-tools, sync vs async, subagent inputs/outputs, checkpointing & the state-inspection limitation
- `.../multi-agent/handoffs.md` — `Command.PARENT` handoffs, the `AIMessage`+`ToolMessage` pairing requirement
- `.../multi-agent/router.md` — `Command` vs `Send` routing, stateless vs stateful
- `.../multi-agent/skills.md`, `.../multi-agent/custom-workflow.md`
- `https://docs.langchain.com/oss/python/migrate/langgraph-supervisor.md` — "no longer actively maintained"

**LangGraph**
- `https://docs.langchain.com/oss/python/langgraph/graph-api.md` — State/schemas/reducers, private channels + the streaming caveat, `Send`, `Command` (incl. `graph=Command.PARENT`), recursion limit
- `.../langgraph/use-graph-api.md` — map-reduce with `Send`, `defer=True`, parallel branches, `max_concurrency`
- `.../langgraph/use-subgraphs.md` — the two communication modes, subgraph persistence table, `View subgraph state` limitation
- `.../langgraph/checkpointers.md` — threads, super-steps, state history, durability modes, checkpointer libraries
- `.../langgraph/use-time-travel.md` — replay vs fork, and the "replay re-executes" warning
- `.../langgraph/stores.md`, `.../langgraph/persistence.md`, `.../langgraph/workflows-agents.md` (orchestrator-worker, parallelization)
- `.../langgraph/errors/MULTIPLE_SUBGRAPHS.md`, `.../errors/INVALID_CONCURRENT_GRAPH_UPDATE.md`
- Redirect check: `https://langchain-ai.github.io/langgraph/concepts/multi_agent/` → `.../oss/python/langgraph/graph-api`

**Deep Agents**
- `https://docs.langchain.com/oss/python/deepagents/overview.md` — core capabilities; task planning opt-in from v0.7
- `.../deepagents/subagents.md` — `SubAgent` / `CompiledSubAgent` field tables, general-purpose subagent, running without subagents
- `.../deepagents/backends.md` — StateBackend / FilesystemBackend / StoreBackend / CompositeBackend, namespace factories
- `.../deepagents/memory.md`, `.../deepagents/async-subagents.md`, `.../deepagents/human-in-the-loop.md`
- Source: `github.com/langchain-ai/deepagents` @ `main` — `libs/deepagents/deepagents/graph.py` (`create_deep_agent` signature, `DeepAgentState`), `libs/deepagents/deepagents/middleware/subagents.py` (`SubAgent:38`, `CompiledSubAgent:169`, `TASK_TOOL_DESCRIPTION:287`, `GENERAL_PURPOSE_SUBAGENT:303`, `task:544`, `SubAgentMiddleware:610`), `_version.py` (`0.7.9`)

**Libraries**
- `github.com/langchain-ai/langgraph-supervisor-py` — `README.md` (deprecation note), `Command.PARENT` handoff at `:258`
- `github.com/langchain-ai/langgraph-swarm-py` — `README.md`, handoff at `:164`

**Installed-version checks** (`v2/.venv`, langgraph 1.2.11)
- `StateGraph.__init__` / `.add_node` / `.compile` / `.ainvoke` signatures; `Command.PARENT == "__parent__"`; `Send`, `RetryPolicy`, `interrupt`, `get_stream_writer`, `InMemorySaver`, `InMemoryStore` all importable; `SqliteSaver` and `deepagents` **not** installed
- `langgraph/pregel/_executor.py:135` — `config.get("max_concurrency")` reads the top-level key, contradicting the docs example

**Skills** (`.claude/skills/`, read as instructed)
- `ecosystem-primer` — the three-layer model and the "load live docs, don't trust training data" rule this document follows
- `langgraph-fundamentals` — state/reducers/`Command`/`Send`, the `Command`-plus-static-edge warning, error-handling tiers
- `langgraph-persistence` — checkpointer selection, subgraph scoping table, `update_state` vs `Overwrite`, `runtime.store`
- `deep-agents-core`, `deep-agents-orchestration` — `create_deep_agent` config surface, subagent statelessness, HITL requires a checkpointer (**see §9.1 for where these are stale**)
- `swarm` — unrelated to `langgraph-swarm`; see §9.1

**NetGent**
- `v2/src/netgent/agent/{orchestrator.py, llm.py}`, `agent/explore_agent/{graph.py, browser_agent.py, sweep.py}`, `agent/workflow_generator_agent/compiler.py`, `agent/validation_agent/validate.py`, `cli/generate.py`, `executor/engine.py`, `browser/dom/models.py`, `schema/workflow.py`, `evals/{stress.py, matrix.py}`, `tests/unit/test_import_boundaries.py`, `pyproject.toml`
- `v2/docs/OVERVIEW.md` §3.1 (the compile-side pipeline and the Discovery fleet), §4.1–4.3 (the T0–T3 repair ladder), §7 (what is still unspecified)
- `CLAUDE.md` — the hard rules this recommendation is written to respect
