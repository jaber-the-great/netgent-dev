# How people actually build LangGraph agents — classes or functions? — and what NetGent should do

**Question.** Do real LangGraph agents wrap themselves in a class (`class Agent: self.graph = self._build_graph()`),
or are they functions plus a compiled graph? Where does a *live resource* (our Playwright session) go? Where does
cross-run memory go? Where does configuration go? Should the orchestrator embed the explorer as a subgraph? What
should `explorer/agent.py`, `explorer/graph.py` and `orchestrator.py` look like?

**Status.** Written 2026-08-28. Every upstream claim is pinned to a commit SHA or a live docs URL fetched the same
day; every "measured" claim is a probe I ran against the versions installed in `v2/.venv`
(`langgraph 1.2.11`, `langgraph-checkpoint 4.2.0`, `langgraph-prebuilt 1.1.0`, `langchain 1.3.15`,
`langchain-core 1.5.5` — `v2/pyproject.toml:23-29`). This doc is the *structural* companion to
[`langgraph-multi-agent.md`](langgraph-multi-agent.md) (which covers **which** patterns — supervisor/swarm/
handoffs/custom workflow) and [`browser-agent-architectures.md`](browser-agent-architectures.md) (which covers
**role decomposition**). It deliberately does not re-derive either; it covers the axis they don't — **the shape of
the Python**.

---

## Summary (10 lines)

1. **Nobody at LangChain ships an agent class.** Every first-party artifact is *functions + a compiled graph*:
   `create_agent`, `create_deep_agent`, `create_swarm`, `create_agent` (bigtool), `langmem.create_*`, the
   `react-agent` / `new-langgraph-project` templates, `open_deep_research`. The only first-party classes are
   **schemas** (`AgentState`, `SwarmState`, `Configuration`), **middleware** (`AgentMiddleware`), and things that
   **own a live OS resource** (`langmem.LocalReflectionExecutor` — a thread + queue).
2. `langgraph.prebuilt.create_react_agent` is **deprecated** in favour of `langchain.agents.create_agent` — the
   migration was function → function, never function → class.
3. **Classes do appear widely in the wild** (108+ GitHub hits for `self.graph = self._build_graph()`, incl.
   CopilotKit's own examples, `google/adk-python`, `hashgraph/guardian`), and every serious *browser* agent is a
   class — browser-use `Agent`, Skyvern `ForgeAgent`, Magentic-UI `FaraWebSurfer`, Agno `Agent` — but those are
   frameworks *without* LangGraph. The one LangGraph browser agent that is a class (`openbrowser-ai`) keeps only
   control-flow counters in state and reaches the browser through `self.agent`.
4. **LangGraph's own documented answer for a live resource is `Runtime.context`**: "Static context for the graph
   run, like `user_id`, `db_conn`, etc. … can also be thought of as **'run dependencies'**"
   (`langgraph/runtime.py:198-201`). `config["configurable"]` is deprecated (v0.6.0, removal v2.0.0).
5. **Measured:** a non-picklable live object passed via `context=` works fine *with a checkpointer attached* —
   context is never checkpointed, only state is (§3a probe). That single fact resolves NetGent's design.
6. **Measured:** `await subgraph.ainvoke()` inside a node is observationally identical to `add_node(subgraph)` for
   streaming namespaces, interrupt propagation and `get_state(subgraphs=True)`. The *only* thing you lose is
   **static** visibility — and only if the graph is built *inside* the node body, as ours is (§3d probes).
7. **Measured:** NetGent's `AgentState` is already checkpointer-clean (`DomSnapshot`, `AgentStep`, `set[str]` all
   round-trip through `JsonPlusSerializer`). The closures are the only blocker to persistence.
8. **Measured:** `graph.get_graph().draw_mermaid()` already renders both NetGent graphs correctly — the honest
   replacement for the hand-mirrored mermaid deleted in `70a3a3b` / `0a70be2`, and a cheap snapshot test.
9. **Recommendation:** keep `AgentTrajectory`/`AgentStep`/`StepRecord` as models; keep **one small class**
   (`ExplorerMemory`) because it owns an `asyncio.Task` with a lifecycle; make the explorer a **module-level
   compiled graph** whose nodes read the session/LLM from a frozen `ExplorerContext` dataclass; keep `explore()` as
   the single `run()`-shaped API for the CLI and the sweep; keep the orchestrator a factory (Platform supports
   factories) and let its `explore` node close over the module-level explorer so xray sees it.
10. Everything I could not verify is in §7.

---

## 0. Method

Read first, in this order: `CLAUDE.md`, `v2/src/netgent/agent/explorer/agent.py`,
`v2/src/netgent/agent/explorer/graph.py`, `v2/src/netgent/agent/llm.py`, `v2/src/netgent/agent/orchestrator.py`,
then `.claude/skills/{ecosystem-primer,langgraph-fundamentals,langgraph-persistence,langgraph-cli,
langchain-fundamentals,deep-agents-core,deep-agents-memory,deep-agents-orchestration}/SKILL.md`.

Upstream source was fetched from `raw.githubusercontent.com` / the GitHub API on 2026-08-28, pinned to:

| Repo | SHA (short) | Date |
|---|---|---|
| `langchain-ai/react-agent` | `9bbd82d84905` | 2026-08-28 |
| `langchain-ai/new-langgraph-project` | `f7e2ee300d48` | 2026-08-21 |
| `langchain-ai/open_deep_research` | `1b7d2e80db9f` | 2026-08-10 |
| `langchain-ai/deepagents` | `a1af029e6e73` | (repo HEAD when fetched) |
| `langchain-ai/langgraph` | `11ee185999b8` / archive `23961cff61a4` | — |
| `langchain-ai/langgraph-swarm-py` | `749d4450f248` | 2026-07-15 |
| `langchain-ai/langgraph-supervisor-py` | `88859b34017a` | 2026-07-15 |
| `langchain-ai/langgraph-bigtool` | `0bb7f9227d34` | 2026-07-15 |
| `langchain-ai/langmem` | `29cbe41e5852` | 2026-08-11 |
| `browser-use/browser-use` | `7cdc4dcd5d7a` | — |
| `Skyvern-AI/skyvern` | `96618fc406df` | — |
| `microsoft/magentic-ui` | `d3c9d13c3928` | — |
| `billy-enrizky/openbrowser-ai` | `168d43e3aa95` | — |
| `agno-agi/agno` | `c96291cbd0f6` | — |
| `CopilotKit/CopilotKit` | `64181a34b91e` | — |

Where docs and installed source disagree I cite the file in `.venv`. Probe scripts are reproduced inline so the
numbers can be re-run.

---

## 1. What LangChain itself ships

### 1.1 The two official templates: dataclass context, module-level compiled graph

`langchain-ai/react-agent` — the template `langgraph new --template agent-python` produces. **No class anywhere
except the schemas.**

`src/react_agent/graph.py` ends with:

```python
builder = StateGraph(State, input_schema=InputState, context_schema=Context)
builder.add_node(call_model)
builder.add_node("tools", ToolNode(TOOLS))
builder.add_edge("__start__", "call_model")
builder.add_conditional_edges("call_model", route_model_output)
builder.add_edge("tools", "call_model")
graph = builder.compile(name="ReAct Agent")            # module-level, compiled once
```

The node is a plain async function that takes the runtime, not `self`:

```python
async def call_model(state: State, runtime: Runtime[Context]) -> Dict[str, List[AIMessage]]:
    model = load_chat_model(runtime.context.model).bind_tools(TOOLS)
    system_message = runtime.context.system_prompt.format(system_time=datetime.now(tz=UTC).isoformat())
```

`src/react_agent/context.py` — configuration is a **frozen-ish dataclass with per-field metadata and env-var
fallback**, not pydantic:

```python
@dataclass(kw_only=True)
class Context:
    system_prompt: str = field(default=prompts.SYSTEM_PROMPT, metadata={"description": "..."})
    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="anthropic/claude-sonnet-4-5-20250929", metadata={"description": "..."})
    max_search_results: int = field(default=10, metadata={"description": "..."})

    def __post_init__(self) -> None:
        for f in fields(self):
            if getattr(self, f.name) == f.default:
                setattr(self, f.name, os.environ.get(f.name.upper(), f.default))
```

`src/react_agent/state.py` — state is a `@dataclass` with `Annotated[..., add_messages]` and a narrower
`InputState` base class. Its comment is the template's own advice on what state is for:

```python
    # Additional attributes can be added here as needed.
    # Common examples include:
    # retrieved_documents: List[Document] = field(default_factory=list)
    # extracted_entities: Dict[str, Any] = field(default_factory=dict)
    # api_connections: Dict[str, Any] = field(default_factory=dict)
```

(Note `api_connections` — the template *does* contemplate resources in state. See §3a for why that only works
without a checkpointer.)

`langgraph.json` is four lines and points at the module-level variable:

```json
{ "$schema": "https://langgra.ph/schema.json", "dependencies": ["."],
  "graphs": { "agent": "./src/react_agent/graph.py:graph" }, "env": ".env" }
```

`langchain-ai/new-langgraph-project` is the same shape with a `TypedDict` context instead of a dataclass:

```python
class Context(TypedDict):
    my_configurable_param: str

async def call_model(state: State, runtime: Runtime[Context]) -> Dict[str, Any]:
    return {"changeme": f"... {(runtime.context or {}).get('my_configurable_param')}"}

graph = (StateGraph(State, context_schema=Context)
         .add_node(call_model).add_edge("__start__", "call_model").compile(name="New Graph"))
```

**Both templates use exactly NetGent's fluent-chained-`.compile()` style** — `graph.py:317-324` and
`orchestrator.py:197-205` are idiomatic as written. The difference is only *when* they compile (import time vs per
run) and *how* nodes reach their dependencies (`runtime.context` vs closure).

### 1.2 `create_react_agent` → `create_agent`: function to function

`langgraph.prebuilt.create_react_agent` is **deprecated in the installed 1.2.11**
(`langgraph/prebuilt/chat_agent_executor.py:274-277`):

```python
@deprecated(
    "create_react_agent has been moved to `langchain.agents`. Please update your import to "
    "`from langchain.agents import create_agent`.",
    category=LangGraphDeprecatedSinceV10,
)
def create_react_agent(...) -> CompiledStateGraph:
```

So are the state schemas — `AgentState`, `AgentStatePydantic`, `AgentStateWithStructuredResponse` all carry
`@deprecated("... moved to `langchain.agents`")` (`chat_agent_executor.py:53-105`).

The replacement is still a function returning a compiled graph
(`langchain/agents/factory.py:768-853`, four `@overload`s):

```python
def create_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    response_format: ...,
    state_schema: ...,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    ...
) -> CompiledStateGraph[AgentState[Any], ContextT, InputAgentState, OutputAgentState[Any]]: ...
```

The extension point they added instead of subclassing is `AgentMiddleware` — a **class**, but a class of *hooks*,
not of *the agent*. Nuno Campos and the LangChain team state the reason explicitly
([langchain.com/blog/agent-middleware](https://www.langchain.com/blog/agent-middleware), 2025-09-08): "while it is
simple to get a basic agent abstraction up and running, it is hard to make this abstraction flexible enough" —
middleware lets you customise sequentially rather than accumulating interdependent constructor parameters. Hooks:
`before_model`, `after_model`, `modify_model_request`.

The design principle behind all of it, from
[langchain.com/blog/building-langgraph](https://www.langchain.com/blog/building-langgraph) (Nuno Campos,
2025-09-04): "**It should feel like writing code.**" and "The runtime of the library is independent from the
developer SDKs." Nodes are "subscriber functions executing when dependencies change"; checkpoints are
"**serializable** … enabling resumption across machines". That last word is the constraint that decides §3a/§3b.

### 1.3 `deepagents` — the biggest first-party harness is one function

`libs/deepagents/deepagents/graph.py` @ `a1af029e6e73`. Module docstring: "Provides `create_deep_agent`, the main
entry point for constructing a fully configured deep agent". The **only class in the file is a state schema**
(`DeepAgentState`). The function:

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None, memory: list[str] | None = None,
    permissions: list[FilesystemPermission] | None = None,
    backend: BackendProtocol | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    response_format: ..., state_schema: type[DeepAgentState] | None = None,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None, store: BaseStore | None = None,
    debug: bool = False, name: str | None = None, cache: BaseCache | None = None,
) -> CompiledStateGraph[AgentState[ResponseT], ContextT, InputAgentState, OutputAgentState[ResponseT]]
```

…and its body ends in `return create_agent(...).with_config({"recursion_limit": 9_999, "metadata": {...}})`.
`libs/ARCHITECTURE.md` states the layering flatly: "Deep Agents is an opinionated harness *on top of*
`create_agent()`. It does not introduce a new runtime."

`SubAgentMiddleware` (`libs/deepagents/deepagents/middleware/subagents.py`) is a class
(`class SubAgentMiddleware(AgentMiddleware[Any, ContextT, ResponseT])`) whose ctor is
`(*, backend, subagents, system_prompt=None, task_description=None, private_state_keys=None, state_schema=None)`.
Two subagent forms: `SubAgent` (a TypedDict: name/description/system_prompt/tools/…) and **`CompiledSubAgent`**
(name/description/**`runnable`** — "A custom agent implementation" created via `create_agent()` *or a custom
LangGraph graph*, whose state schema must have a `messages` key).

**Directly relevant to §3d:** the `task` tool dispatches by `await subagent.ainvoke(subagent_state,
subagent_config)`. LangChain's own flagship harness delegates to a child compiled graph **by invoking it inside a
tool/node** — not by `add_node`. That is exactly what `orchestrator.explore` does with `agent.run()`.

Backends (`deep-agents-memory/SKILL.md:9-23`): `StateBackend` (ephemeral, within a thread), `StoreBackend`
(persists across threads/sessions), `CompositeBackend` (route paths). Note the three-way split — it is the same
three-way split as §3b.

### 1.4 `langgraph-swarm` alive, `langgraph-supervisor` deprecated

`langgraph_swarm/swarm.py` @ `749d4450f248`: one class, one function.

```python
class SwarmState(MessagesState):
    """State schema for the multi-agent swarm."""
    active_agent: str | None

def create_swarm(agents: list[Pregel], *, default_active_agent: str,
                 state_schema: StateSchemaType = SwarmState,
                 context_schema: type[Any] | None = None, **deprecated_kwargs) -> StateGraph:
```

Note it returns an **uncompiled `StateGraph`** — the caller compiles, so the caller owns the checkpointer/store.
`langgraph_swarm/handoff.py`'s `create_handoff_tool(*, agent_name, name=None, description=None) -> BaseTool`
returns a tool whose body is `Command(goto=agent_name, graph=Command.PARENT, update={...})`.

`langgraph-supervisor-py` @ `88859b34017a` README carries a deprecation: use "the supervisor pattern directly via
tools rather than this library for most use cases", pointing at the LangChain multi-agent guide; they keep it
LangChain-1.0-compatible only to help upgrades. **Why it matters here:** the deprecation reason is *the class-like
prebuilt was less flexible than writing the tool yourself* — the same argument that killed `create_react_agent`
in favour of `create_agent` + middleware. There is a consistent institutional bias: fewer wrappers, more
composition. (Already recorded in [`langgraph-multi-agent.md`](langgraph-multi-agent.md) §1.)

### 1.5 `open_deep_research` — the biggest first-party *application*

`src/open_deep_research/deep_researcher.py` @ `1b7d2e80db9f`. **Zero agent classes.** Eight module-level async node
functions (`clarify_with_user`, `write_research_brief`, `supervisor`, `supervisor_tools`, `researcher`,
`researcher_tools`, `compress_research`, `final_report_generation`), three builders, three module-level compiled
graphs, and the parent **embeds children with `add_node`**:

```python
supervisor_builder = StateGraph(SupervisorState, config_schema=Configuration)
supervisor_builder.add_node("supervisor", supervisor)
supervisor_builder.add_node("supervisor_tools", supervisor_tools)
supervisor_builder.add_edge(START, "supervisor")
supervisor_subgraph = supervisor_builder.compile()

researcher_builder = StateGraph(ResearcherState, output=ResearcherOutputState, config_schema=Configuration)
...
researcher_subgraph = researcher_builder.compile()

deep_researcher_builder = StateGraph(AgentState, input=AgentInputState, config_schema=Configuration)
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)
deep_researcher_builder.add_node("write_research_brief", write_research_brief)
deep_researcher_builder.add_node("research_supervisor", supervisor_subgraph)   # <— compiled graph AS a node
deep_researcher_builder.add_node("final_report_generation", final_report_generation)
...
deep_researcher = deep_researcher_builder.compile()
```

Config is **pydantic** here, not a dataclass — `class Configuration(BaseModel)` with a hand-rolled adapter:

```python
@classmethod
def from_runnable_config(cls, config: Optional[RunnableConfig] = None) -> "Configuration":
    configurable = config.get("configurable", {}) if config else {}
    field_names = list(cls.model_fields.keys())
    values: dict[str, Any] = {
        field_name: os.environ.get(field_name.upper(), configurable.get(field_name))
        for field_name in field_names}
    return cls(**{k: v for k, v in values.items() if v is not None})
```

…with UI hints in field metadata (`x_oap_ui_config`: sliders, selects). `langgraph.json` points at
`./src/open_deep_research/deep_researcher.py:deep_researcher`.

Caveat: it still uses the **deprecated** `config_schema=` and `input=`/`output=` kwargs, so it is a *pattern*
reference, not an API reference. `config_schema` warns and maps to `context_schema`
(`langgraph/graph/state.py:227-232`): "`config_schema` is deprecated and will be removed. Please use
`context_schema` instead" — deprecated v0.6.0, removal v2.0.0 (`state.py:149-157`).

### 1.6 `langgraph-bigtool` and `langmem` — the closure precedent, and the one real class

`langgraph-bigtool/langgraph_bigtool/graph.py` @ `0bb7f9227d34`:

```python
class State(MessagesState):
    selected_tool_ids: Annotated[list[str], _add_new]

def create_agent(llm: LanguageModelLike, tool_registry: dict[str, BaseTool | Callable], *,
                 limit: int = 2, filter: dict[str, any] | None = None,
                 namespace_prefix: tuple[str, ...] = ("tools",),
                 retrieve_tools_function: Callable | None = None,
                 retrieve_tools_coroutine: Callable | None = None) -> StateGraph:
    ...
    builder = StateGraph(State)
    builder.add_node("agent", RunnableCallable(call_model, acall_model))
    builder.add_node("select_tools", select_tools_node)
    builder.add_node("tools", tool_node)
    ...
    return builder                                  # uncompiled: caller supplies the store
```

**`tool_registry` and `llm` are captured in closures** over `call_model` / `select_tools` / `should_continue`;
`store` is injected by LangGraph. This is the exact shape of NetGent's `build_agent_graph(agent, session, task,
...)` — closure-over-config, returned builder. It is a *sanctioned* pattern. Note the difference that matters: a
`tool_registry` is inert and process-lifetime; a Playwright session is live and per-run.

`langmem` @ `29cbe41e5852`, `src/langmem/__init__.py` — the public API is *nine* `create_*` functions and **one
name that is a class-ish**: `ReflectionExecutor`. Read the source (`src/langmem/reflection.py`) and it is in fact
an **overloaded factory function** (lines 90-140) that returns one of two classes:

```python
class LocalReflectionExecutor:
    """Handles local reflection tasks with queuing and cancellation support."""
    def __init__(self, reflector: Runnable, store: BaseStore | None):
        ...
        self._task_queue = queue.PriorityQueue()
        self._pending_tasks: dict[str, PendingTask] = {}
        self._worker_running = True
        self._worker = threading.Thread(target=functools.partial(_process_queue, self), daemon=False)
        self._worker.start()
        self._store_lock = threading.Lock()
```

**This is the single clearest statement of LangChain's implicit rule**: a class exists when it owns a *live OS
resource with a lifecycle* (a thread, a queue, a lock). Anything graph-shaped is a function. NetGent's
`Agent.start_watch` / `stop_watch` / `_watch: asyncio.Task` (`explorer/agent.py:157-166`) is precisely that kind of
resource — and, per this rule, precisely the part that should *stay* a class.

### 1.7 The archived examples, and LangChain's own browser agent

`langchain-ai/langgraph/examples/` is now a graveyard. `examples/README.md` @ `11ee185999b8`: "This directory is
retained purely for archival purposes and is no longer updated. The examples previously found here have been moved
to the newly consolidated LangChain documentation." Every notebook (`customer-support`, `plan-and-execute`,
`reflection`, `rag`, `multi_agent`, `web-navigation`, …) is a ~1 KB stub with a link. `docs/docs/` no longer exists
on `main`.

The one worth reading is the **WebVoyager** browser agent, archived at
`23961cff61a42b52525f3b20b4094d8d2fba1744:docs/docs/tutorials/web-navigation/web_voyager.ipynb`. It is the only
first-party LangGraph browser agent, and it answers §3a in the most direct way possible — **the live Playwright
`Page` is a field of graph state**:

```python
class AgentState(TypedDict):
    page: Page  # The Playwright web page lets us interact with the web environment
    input: str  # User request
    img: str  # b64 encoded screenshot
    bboxes: List[BBox]  # The bounding boxes from the browser annotation function
    prediction: Prediction  # The Agent's output
    scratchpad: List[BaseMessage]
    observation: str  # The most recent response from a tool

async def click(state: AgentState):
    page = state["page"]
    ...

graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent)
graph_builder.add_edge(START, "agent")
graph_builder.add_node("update_scratchpad", update_scratchpad)
graph_builder.add_edge("update_scratchpad", "agent")
for node_name, tool in tools.items():
    graph_builder.add_node(node_name, RunnableLambda(tool) | (lambda observation: {"observation": observation}))
    graph_builder.add_edge(node_name, "update_scratchpad")
graph_builder.add_conditional_edges("agent", select_tool)
graph = graph_builder.compile()          # module-level, compiled once

# invocation
page = await browser.new_page()
event_stream = graph.astream({"page": page, "input": question, "scratchpad": []},
                             {"recursion_limit": max_steps})
```

Note the consequences: the graph is a **module-level singleton** (good — Studio-visible, `langgraph.json`-able), the
per-run resource travels **in the first state payload** (so no closure and no rebuild), and there is **no
checkpointer** (there cannot be — `Page` will not serialize). NetGent gets the same "compile once" benefit by
putting the session in `context` instead, and keeps the checkpointer option open. See §3a.

### 1.8 `langgraph.json` / Platform: factory functions are explicitly supported

The CLI reference ([docs.langchain.com/langsmith/cli](https://docs.langchain.com/langsmith/cli)) says the `graphs`
value may be either:

> `./your_package/your_file.py:variable`, where `variable` is an instance of `langgraph.graph.state.CompiledStateGraph`

or

> `./your_package/your_file.py:make_graph`, where `make_graph` is a function that takes a config dictionary
> (`langchain_core.runnables.RunnableConfig`) and returns an instance of `langgraph.graph.state.StateGraph`

The graph-rebuild page ([docs.langchain.com/langsmith/graph-rebuild](https://docs.langchain.com/langsmith/graph-rebuild))
shows the async form and the injection rule:

```python
async def make_graph(config: RunnableConfig, runtime: ServerRuntime):
    user = runtime.ensure_user()
    return make_graph_for_user(user.identity)
```

> "the server inspects your function's type annotations to determine which arguments to inject."

and — the sentence NetGent should tape to the wall —

> **"In most cases, customization is best handled by conditioning on the config within individual nodes rather than
> dynamically changing the whole graph structure. This makes it easier to test and manage."**

plus the hard constraint: the returned graph must keep **the same topology** (nodes, edges, state schema) across
calls, or state and introspection break.

That is a direct verdict on NetGent's `build_agent_graph(...)` / `build_orchestration_graph(...)`: the *factory* is
allowed, but the reason we rebuild (to close over a per-run session) is the reason the docs advise against
rebuilding. Condition inside the nodes instead — via `Runtime.context`.

The `langgraph-cli` skill's key table agrees (`langgraph-cli/SKILL.md`, `graphs` row): "The variable must be a
`CompiledGraph` **or a function returning one**."

### 1.9 `Runtime` / `context_schema` — what replaced `config["configurable"]`

Installed source, `langgraph/runtime.py:198-201`:

```python
    context: ContextT = field(default=None)
    """Static context for the graph run, like `user_id`, `db_conn`, etc.

    Can also be thought of as 'run dependencies'."""
```

The `Runtime` dataclass also carries `store: BaseStore | None`, `stream_writer`, `heartbeat`, `previous`,
`execution_info`, `server_info`, `control` (`runtime.py:198-240`). Its own docstring example is the canonical
pattern:

```python
graph = (StateGraph(state_schema=State, context_schema=Context)
         .add_node("personalized_greeting", personalized_greeting)
         ...).compile(store=store)
result = graph.invoke({}, context=Context(user_id="user_123"))
```

`StateGraph.__init__` accepts `context_schema: type[ContextT] | None`, documented as: "Use this to expose immutable
context data to your nodes, like `user_id`, `db_conn`, etc." (`langgraph/graph/state.py:149-153`).
`config_schema` is deprecated with a warning at `state.py:227-232`.

The docs page [docs.langchain.com/oss/python/langchain/runtime](https://docs.langchain.com/oss/python/langchain/runtime)
lists what belongs in context in one line: "**Context**: static information like user id, **db connections**, or
other dependencies for a agent invocation."

Motivation, from the RFC ([langgraph#5023](https://github.com/langchain-ai/langgraph/issues/5023), Sydney Runkle,
2025-06-09): "Specifying immutable dependencies for a graph run via `config["configurable"]` is unintuitive and
unnecessarily nested" — described as "the #1 developer pain point we hear about in community feedback". Before/after:

```python
agent.invoke(state, config={"configurable": {"user_id": "user_123"}})   # before
agent.invoke(state, config={"thread_id": "12345"}, context={"user_id": "user_123"})   # after
```

**Gotcha worth writing down** (`langgraph/_internal/_runnable.py:230-243`): injection is by **parameter name**, not
by annotation alone — "For a keyword to be injected from the config object, the function signature must contain a
kwarg with **the same name** and a matching type annotation." A node written `def observe(s, rt: Runtime[Ctx])`
raises `TypeError: observe() missing 1 required positional argument: 'rt'`. It must be named `runtime` (likewise
`config`, `store`, `writer`). I hit this while probing; it costs ten minutes if you don't know.

### 1.10 The Functional API (`@entrypoint` / `@task`)

`langgraph/func/__init__.py:1-56` — `__all__ = ("task", "entrypoint")`; `class entrypoint(Generic[ContextT])` at
`:262`, `def task(...)` at `:110-132`. The entrypoint docstring says the decorated function takes a single input
parameter and may request injected `config`, `previous`, `runtime`; `previous` is "the return value of the previous
invocation of the entrypoint on the same thread id … only available when a checkpointer is provided".

[docs.langchain.com/oss/python/langgraph/functional-api](https://docs.langchain.com/oss/python/langgraph/functional-api)
gives the trade:

- Control flow: "The Functional API does not require thinking about graph structure. You can use standard Python
  constructs to define workflows."
- State: "@entrypoint and @tasks do not require explicit state management as their state is scoped to the function."
- Checkpointing: "In the Graph API a new checkpoint is generated after every superstep. In the Functional API, when
  tasks are executed, their results are saved to an existing checkpoint associated with the given entrypoint
  instead of creating a new checkpoint."
- **Visualization: "The Graph API makes it easy to visualize the workflow as a graph … The Functional API does not
  support visualization as the graph is dynamically generated during runtime."**

**Who uses it:** none of the first-party artifacts surveyed above. `react-agent`, `new-langgraph-project`,
`open_deep_research`, `deepagents`, `langgraph-swarm`, `langgraph-bigtool` are all Graph API. I found no
first-party `@entrypoint` template. Verdict for NetGent in §3f.

---

## 2. Third-party: where the classes actually live

### 2.1 LangGraph projects that wrap the graph in a class — 108+ of them

GitHub code search, 2026-08-28: `"self.graph = self._build_graph" language:python` → **108 files**;
`"self.graph = self._build_graph()" "StateGraph"` → **90**. The canonical shape, from CopilotKit's own showcase
(`examples/showcases/a2a-travel/agents/itinerary_agent.py` @ `64181a34b91e`):

```python
class ItineraryAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ItineraryState)
        workflow.add_node("parse_request", self._parse_request)
        ...
```

Same file shape in `CopilotKit/CopilotKit:examples/integrations/a2a-middleware/agents/research_agent.py`
(`class ResearchAgent`), `google/adk-python:src/google/adk/workflow/_workflow.py` (a pydantic model that builds its
graph in `model_post_init`), `hashgraph/guardian:.../single_document_pipeline.py`
(`def _build_graph(self) -> CompiledStateGraph`), and dozens of smaller repos. Nearly all of them do it for the same
reason NetGent does: **the nodes need something the graph API has no slot for** (an LLM handle, a retriever, a
service client, a project root).

Two structural sub-variants show up:

- **Nodes as bound methods** (`workflow.add_node("parse_request", self._parse_request)`) — the majority.
- **Compile inside vs outside**: some return `builder` and compile at call time
  (`self.app = self.graph.compile(checkpointer=self.memory)` in `nehachaudhari20/RedBlue`), some compile in
  `_build_graph`.

### 2.2 The one that is closest to NetGent: `openbrowser-ai`

`billy-enrizky/openbrowser-ai:src/openbrowser/agent/graph.py` @ `168d43e3aa95` — a browser-use-shaped agent whose
loop is a LangGraph `StateGraph`:

```python
class AgentGraphBuilder:
    """Optimized LangGraph agent with minimal overhead."""
    __slots__ = ('agent', 'graph', '_has_downloads', '_max_failures')

    def __init__(self, agent: 'Agent'):
        self.agent = agent
        self._has_downloads = agent.has_downloads_path
        self._max_failures = agent.settings.max_failures + int(...)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build minimal StateGraph: START -> step -> [continue/done/error]."""
        graph = StateGraph(GraphState)
        graph.add_node("step", self._step_node)
        graph.add_edge(START, "step")
        graph.add_conditional_edges("step", self._should_continue,
                                    {"continue": "step", "done": END, "error": END})
        return graph.compile()

    async def run(self, max_steps: int = 100) -> AgentHistoryList:
        state: GraphState = {...}
        await self.graph.ainvoke(state, config={"recursion_limit": max_steps + 10})
        return self.agent.history
```

```python
class GraphState(TypedDict, total=False):
    """Minimal state for LangGraph workflow."""
    step_number: int
    max_steps: int
    is_done: bool
    consecutive_failures: int
```

Read the trade it made: **state carries only control-flow counters; all real data lives on `self.agent`.** The
browser session is reached as `agent.browser_session.…` inside `_step_node`. That is a legitimate third arm of the
design space — and it is strictly *less* introspectable than NetGent's current graph, whose `AgentState` at least
carries the trajectory, observation and stuck counters (`graph.py:70-85`). We are already ahead of the closest
public analogue.

### 2.3 The non-LangGraph browser agents: all classes, all resource-owning

| Project | Shape | Resource | Cite |
|---|---|---|---|
| browser-use | `class Agent(Generic[Context, AgentStructuredOutput])`, `@time_execution_sync('--init') def __init__` | `browser_session` on `self` | `browser_use/agent/service.py` @ `7cdc4dcd5d7a` |
| browser-use state | `class AgentSettings(BaseModel)`, `class AgentState(BaseModel)` — "Holds all state information for an Agent" | — | `browser_use/agent/views.py` |
| Skyvern | `ForgeAgent` (`skyvern/forge/agent.py`), used as `agent.execute_step(...)`, `agent.handle_potential_OTP_actions(...)`, `ForgeAgent.record_artifacts_after_action(...)` | app-level singleton | `tests/unit/helpers.py`, `tests/unit/test_agent_otp_routing.py` @ `96618fc406df` |
| Magentic-UI | `class FaraWebSurfer:` (`__init__` at :66) holding `self._browser` (:82), `self._context` (:183), `self._browser_started` (:110), lazy `__aenter__` (:161), `_save_state()` (:244), teardown `__aexit__` (:301) | Playwright browser + context, explicit lifecycle | `src/magentic_ui/agents/web_surfer/fara/_fara_web_surfer.py` @ `d3c9d13c3928` |
| Agno | `@dataclass(init=False) class Agent:` with ~100 fields | — | `libs/agno/agno/agent/agent.py` @ `c96291cbd0f6` |
| Notte | SDK-side `class AgentsClient(BaseClient)` and a nested `class AgentWorkflow` | remote session id | `packages/notte-sdk/src/notte_sdk/endpoints/agents.py` @ `e2932b2330` |

The pattern is uniform and it is *not* a LangGraph pattern: when your agent owns a browser, the browser's
**lifecycle** (start / attach / save-state / teardown) wants an object. Note that Magentic-UI's `FaraWebSurfer`
keeps the resource *and* the lifecycle *and* the loop in one class — which is why it is 984 lines. NetGent already
does better: `BrowserSession` owns the lifecycle (`browser/session.py`), so the agent doesn't have to.

**Stagehand** I could not verify — see §7.

### 2.4 The team's own position on class-vs-function

I could not verify the discussion I was pointed at (`langchain-ai/langgraph/discussions/4390`, "Prebuilt Agents in
LangGraph: Classes or Functions?"): GitHub Discussions are **disabled** on `langchain-ai/langgraph` as of
2026-08-28 (`hasDiscussionsEnabled: false`, `discussions.totalCount: 0` via the GraphQL API), and the URL 404s.
See §7.1 for the second-hand summary and why I am not treating it as a citation.

What *is* verifiable is the revealed preference, and it is consistent:

1. `create_react_agent` → `create_agent`: function → function, extension via middleware, not subclassing
   (`chat_agent_executor.py:274-277`).
2. `langgraph-supervisor` deprecated in favour of "the supervisor pattern directly via tools" — the wrapper lost to
   composition.
3. The middleware blog's stated reason: a basic agent abstraction is easy, "it is hard to make this abstraction
   flexible enough" ([langchain.com/blog/agent-middleware](https://www.langchain.com/blog/agent-middleware)).
4. The graph-rebuild doc's stated preference: "customization is best handled by conditioning on the config within
   individual nodes rather than dynamically changing the whole graph structure. This makes it easier to test and
   manage."
5. `Runtime.context` exists specifically so nodes can reach `db_conn`-shaped dependencies without a closure or a
   `self` (`runtime.py:199-201`).

That is enough to answer the question without the discussion thread.

---

## 3. NetGent's six questions, answered

First, what we do today, for reference:

| File | Shape |
|---|---|
| `explorer/agent.py:123-263` | `class Agent`: ctor takes `llm, max_steps, run_dir, upload_file, allowed_kinds, max_actions_per_step`; holds `history: list[StepRecord]` (`:153`), `noticed: list[str]` (`:156`), `_watch: asyncio.Task \| None` (`:157`); `run(session, task, url, frame_filter, max_steps)` (`:216`) builds a graph per call (`:237`) and `ainvoke`s it (`:240`) |
| `explorer/graph.py:88-324` | `build_agent_graph(agent, session, task, *, frame_filter, max_steps)` — lazy `from langgraph.graph import …` (`:97`); three async closures over `agent`/`session`/`task`/`history`/`llm`/`allowed`/`max_actions`; `Command` routing; `.compile()` with no checkpointer |
| `orchestrator.py:84-218` | `build_orchestration_graph(req, llm, listen)` — four closures over `req`/`llm`/`run_dir`; `explore` opens `async with BrowserSession(...)` and calls `agent.run(...)` (`:126-127`); `orchestrate()` compiles + `ainvoke({})` |
| `llm.py:41-52` | `LLM` Protocol (`decide`, `judge`); `LangChainLLM` (`:124`) lazily imports langchain; `FakeLLM` (`:249`) replays scripted decisions |

### (a) A node that needs a live Playwright session

**Five strategies exist in the wild.** Ranked by what the surveyed code does:

| # | Strategy | Who does it | Cost |
|---|---|---|---|
| 1 | **In graph state** | WebVoyager (`page: Page` in `AgentState`), react-agent template's own comment (`api_connections`) | Kills the checkpointer forever; state is no longer a value |
| 2 | **Closure, graph rebuilt per run** | **NetGent today**; `langgraph-bigtool.create_agent` closes over `tool_registry` | One compile per run; graph invisible to `get_subgraphs()`/Studio if built inside a node; docs advise against rebuilding |
| 3 | **`Runtime.context`** | react-agent, new-langgraph-project, `create_agent`/`create_deep_agent` (`context_schema=`), LangGraph's own `Runtime` docstring | Node signature must name the kwarg `runtime`; context must be constructed per run |
| 4 | **A class holding the resource, nodes as bound methods** | `openbrowser-ai.AgentGraphBuilder`, CopilotKit examples, `google/adk-python` | Graph is an instance attribute — not a module-level entry point; state tends to shrink to counters |
| 5 | **`config["configurable"]`** | legacy | **Deprecated** v0.6.0, removal v2.0.0 (`langgraph/graph/state.py:227-232`) |

**LangGraph's documented recommendation is #3, in as many words.** `langgraph/runtime.py:199-201`: "Static context
for the graph run, like `user_id`, **`db_conn`**, etc. Can also be thought of as **'run dependencies'**."
`StateGraph`'s own docstring repeats it (`state.py:151-153`), and the docs page spells out "db connections".

**The objection you'd expect — "but our session isn't serializable, so it can't go in `context`" — is false.**
Measured, langgraph 1.2.11:

```python
class Live:                       # stand-in for BrowserSession: NOT picklable
    def __init__(self): self.n = 0
    def __reduce__(self): raise TypeError("not picklable")

@dataclasses.dataclass
class Ctx:
    session: Live
    task: str

def observe(s: S, runtime: Runtime[Ctx]):      # kwarg MUST be named `runtime`
    runtime.context.session.n += 1
    return {"steps": s.get("steps", 0) + 1}

g = (StateGraph(S, context_schema=Ctx).add_node("observe", observe)
     .add_edge(START, "observe").compile(checkpointer=InMemorySaver()))

out = await g.ainvoke({}, {"configurable": {"thread_id": "t"}}, context=Ctx(session=live, task="fill the form"))
```

```
OK, result: {'steps': 1} session touched: 1
checkpointed values: {'steps': 1}
checkpoint has context? False   {'configurable': {'thread_id': 't', 'checkpoint_ns': '', 'checkpoint_id': '...'}}
```

**Context is never checkpointed; only state is.** So a live `BrowserSession` in `Runtime.context` is compatible with
a checkpointer, with `langgraph dev`, and with a module-level compiled graph — all three of which strategy #1
(state) and strategy #2 (closure) cost us.

**And NetGent's state is already checkpointer-clean.** Measured against `JsonPlusSerializer` (ormsgpack —
`langgraph/checkpoint/serde/jsonplus.py`):

```
{'prev_texts': {'a','b'}}  -> msgpack   34 bytes | roundtrip: {'a','b'}
DomSnapshot(...)           -> msgpack  160 bytes | roundtrip type: DomSnapshot | equal: True
AgentStep(...)             -> msgpack  191 bytes | roundtrip type: AgentStep   | equal: True
```

(with a forward-compat warning: "Deserializing unregistered type … will be blocked in a future version … add to
`allowed_msgpack_modules`" — a one-line fix if we ever attach a checkpointer, not a blocker.)

So `AgentState`'s `snapshot: Any` / `prev_texts: set[str]` are **not** the reason we have no checkpointer. The
closures are. Moving `session`/`llm`/`memory` from closure to `context` is the whole change.

**Verdict (a):** move to `Runtime.context`. Keep the graph module-level and compiled once.

### (b) Cross-run memory (`Agent.history` across a 21-form sweep)

Three homes, and LangGraph's own three-way split is the same one deepagents ships as backends
(`deep-agents-memory/SKILL.md:9-11`: `StateBackend` ephemeral-within-thread / `StoreBackend` across threads and
sessions / `CompositeBackend` routed).

| Home | Scope | Survives | Fits our `history`? |
|---|---|---|---|
| **Object attribute** (`Agent.history`, today — `agent.py:153`, mutated in place via `graph.py:100`) | one Python process | nothing | Yes today: `sweep.py:121-131` builds **one** `Agent` and calls `run()` per form; `note()` folds between tasks (`agent.py:172-195`) |
| **Checkpointer thread** (`thread_id`) | one thread, serialized | process restart, machine move | Would work — `StepRecord` is pydantic and round-trips (measured). But a sweep is *N runs of one task each*, so it needs either one long thread or an explicit carry-over |
| **`BaseStore`** (`runtime.store`, namespaced `put/get/search`) | across threads **and** sessions | everything | The idiomatic home for "what I learned on form 2 while working form 7"; `langgraph-persistence/SKILL.md:376-437` |

**What breaks on LangGraph Platform / `langgraph dev`.** The Platform runs your graph in a server process you do not
own, one run at a time, potentially on a different machine per run
("**serializable** checkpoints enabling resumption across machines" —
[building-langgraph](https://www.langchain.com/blog/building-langgraph)). Consequences, in order of severity:

1. **`Agent.history` disappears.** There is no place to keep a long-lived `Agent` instance between runs. The sweep's
   whole value — one memory across 21 forms — is lost silently, not loudly.
2. **`Agent.noticed` and `Agent._watch`** (the settle-watcher `asyncio.Task`, `agent.py:157-166`,
   `graph.py:307-311`) are process-local by nature. These *cannot* move to state or store; they must stay on an
   object (this is the langmem `LocalReflectionExecutor` rule).
3. **The sweep's outer `for` loop** (`sweep.py:123-135`) is plain Python outside any graph. On Platform it would
   have to become either a graph (`Send` fan-out — see [`langgraph-multi-agent.md`](langgraph-multi-agent.md) §5)
   or an external driver calling the deployed graph N times with a shared `thread_id`/store namespace.

**Verdict (b):** for now, keep `history` on an object — but on a **small, explicit `ExplorerMemory` object passed
through `context`**, not on a god-object `Agent`. That makes the Platform migration a two-line change (swap
`ExplorerMemory` for a `BaseStore`-backed implementation behind the same three methods) instead of a rewrite. Do
**not** put `history` in graph state: it is *cross-run* by definition, and graph state is *per-run*.

### (c) Where configuration lives

The two first-party applications disagree, which tells you both are fine:

| | react-agent | open_deep_research |
|---|---|---|
| Type | `@dataclass(kw_only=True) class Context` | `class Configuration(BaseModel)` |
| Per-field docs | `field(metadata={"description": ...})` | `Field(metadata={"x_oap_ui_config": {...}})` |
| Env fallback | `__post_init__` loop over `fields(self)` | `from_runnable_config` classmethod |
| Wired as | `StateGraph(..., context_schema=Context)`, `graph.ainvoke(..., context=Context(...))` | `StateGraph(..., config_schema=Configuration)` (**deprecated spelling**) + `Configuration.from_runnable_config(config)` inside nodes |

`context_schema` is annotated `type[ContextT] | None` (`state.py:219`) with no base-class constraint —
`Runtime`'s own docstring shows a `@dataclass`, `StateGraph`'s shows a `TypedDict`, and `create_deep_agent` takes
`context_schema: type[ContextT]`. **A pydantic `BaseModel` is accepted too** (open_deep_research uses one, just via
the older kwarg). So `GenerateRequest` (`orchestrator.py:37-57`) can be *both* the CLI's flags model *and* the
graph's `context_schema` — one type, two uses, no adapter.

Caveats if we do that:
- `GenerateRequest` already has non-JSON fields (`out: Path`, `trajectory_dir: Path`). Fine for local use (context
  isn't serialized) but Studio/Platform would need to build one from JSON — pydantic handles `Path` on parse, so
  this is fine in practice.
- The `listen: Listener` callback (`orchestrator.py:34`) must **not** go in a pydantic model. Keep it a separate
  context field on a plain dataclass, or keep the orchestrator a factory (§4).

**Verdict (c):** `GenerateRequest` stays and becomes the orchestrator's context. For the explorer, add a small
frozen `ExplorerContext` dataclass — the explorer's config is different in kind (a live session, an `LLM`, a
memory handle) and does not belong in a CLI-flags model.

### (d) Subgraph node vs `agent.run()` inside a node

**Measured, langgraph 1.2.11.** Three shapes, one child graph, `astream(..., subgraphs=True)` with an
`InMemorySaver`:

**A — child compiled at module level, `await child.ainvoke()` inside a node** (what deepagents' `task` tool does):
```
ns=('call_child:9a303eb4-…',) chunk={'c1': {'x': 2}}
ns=('call_child:9a303eb4-…',) chunk={'c2': {'x': 20}}
ns=()                          chunk={'call_child': {'x': 20}}
get_subgraphs: ['call_child']
xray mermaid: subgraph call_child { c1 -> c2 }
```

**B — `add_node("call_child", child)`** (what open_deep_research does):
```
ns=('call_child:aa09f1ca-…',) chunk={'c1': {'x': 2}}
ns=('call_child:aa09f1ca-…',) chunk={'c2': {'x': 20}}
ns=()                          chunk={'call_child': {'x': 20}}
get_subgraphs: ['call_child']
xray mermaid: subgraph call_child { c1 -> c2 }
```

**Identical.** With an `interrupt()` inside the child, both surface it the same way — `__interrupt__` on the stream,
`snap.next == ('call_child',)`, `snap.interrupts == (Interrupt(value='approve?', …),)`, and
`get_state(cfg, subgraphs=True).tasks[0].state` populated in both.

**C — child *built inside the node body*** (what NetGent does — `agent.py:237` calls `build_agent_graph(...)` per
run):
```
get_subgraphs: []
xray mermaid: graph TD; __start__ --> explore; explore --> __end__;      # no expansion
ns=('explore:b1674981-…',) chunk={'c1': {'x': 2}}                        # runtime nesting STILL correct
ns=('explore:b1674981-…',) chunk={'c2': {'x': 20}}
ns=()                       chunk={'explore': {'x': 20}}
```

**So the cost of our current design is precisely one thing: static visibility.** At runtime, `orchestrate()`
already streams and namespaces the explorer correctly. What we lose is `get_subgraphs()`, `get_graph(xray=True)`,
Studio's nested view, and any tooling that reads the graph without running it.

Two other differences from the docs
([use-subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)):

- `add_node(subgraph)` **requires shared state keys** — "the subgraph reads from and writes to the parent's state
  channels automatically". Different schemas need the wrapper-function form anyway
  (`def call_subgraph(state): out = subgraph.invoke({"bar": state["foo"]}); return {"foo": out["bar"]}`).
  NetGent's `OrchestrationState` and `AgentState` share **nothing** — so `add_node(EXPLORER)` is not available to us
  without inventing a shared schema we don't want.
- Subgraph checkpointer scoping: `checkpointer=None` (default, per-invocation, inherits parent for interrupts),
  `True` (per-thread, accumulates), `False` (stateless) — and "Stateful subgraphs (`checkpointer=True`) do NOT
  support calling the same subgraph instance multiple times within a single node"
  (`langgraph-persistence/SKILL.md:273-277`). That last warning matters directly for a sweep, which calls the
  explorer N times.

**Also measured:** `Runtime.context` **does** propagate into a child graph in 1.2.11 — even when the parent declares
no `context_schema`, and whether the child is added as a node or invoked inside one:
```
A parent w/o context_schema: OK {'steps': 1} session.n=1
B parent w/ context_schema : OK {'steps': 1} session.n=1
C invoke-in-node forwarding: OK {'steps': 1} session.n=1
```
(This contradicts [langgraph#5700](https://github.com/langchain-ai/langgraph/issues/5700) "Runtime context is not
being passed to the subgraph" — presumably fixed. I did not read that issue's thread; see §7.)

**Verdict (d):** **keep invoking the explorer inside the node** — deepagents does the same thing, the schemas don't
match anyway, and there is no runtime penalty. But **hoist the compiled explorer to module level** so the node
*closes over* it: that alone converts case C into case A and buys back `get_subgraphs()`, xray, and Studio for free.

### (e) Testing patterns

**What upstream does.** Two levels, both of which NetGent already has an analogue for:

1. **Fake model + graph-level invoke.** `langgraph-bigtool/tests/unit_tests/test_end_to_end.py` @ `0bb7f9227d34`:
   ```python
   from langchain_core.language_models import GenericFakeChatModel, LanguageModelLike

   class FakeModel(GenericFakeChatModel):
       def bind_tools(self, *args, **kwargs) -> "FakeModel":
           """Do nothing for now."""
           return self

   fake_llm = FakeModel(messages=iter([AIMessage("", tool_calls=[{...}]), ...]))
   builder = create_agent(llm, tool_registry, ...)
   ...
   def _validate_result(result: State) -> None:
       assert set(result.keys()) == {"messages", "selected_tool_ids"}
   ```
   Scripted messages, no network, assertions on the **final state dict**. This is structurally the same test as
   `tests/integration/test_agent.py:58-190` with `FakeLLM(script)` — we already do it right.

2. **Module-level graph + context.** `langchain-ai/react-agent/tests/integration_tests/test_graph.py`:
   ```python
   from react_agent import graph
   from react_agent.context import Context

   async def test_react_agent_simple_passthrough() -> None:
       res = await graph.ainvoke({"messages": [("user", "Who is the founder of LangChain?")]},
                                 context=Context(system_prompt="You are a helpful AI assistant."))
   ```
   Note what this buys: the test imports the *same object Platform serves*. Ours can't — `build_agent_graph` needs a
   live session, so today no test can touch the compiled graph without a browser.

**The fakes that exist** (`langchain_core/language_models/fake_chat_models.py`): `FakeMessagesListChatModel:21`,
`FakeListChatModel:59`, `FakeChatModel:192`, `GenericFakeChatModel:227`, `ParrotFakeChatModel:374`. They are
**chat-model-level** fakes. NetGent's seam is one level *above* the chat model (`LLM.decide()` returns a validated
`AgentDecision` — `llm.py:41-52`), so `FakeLLM` (`llm.py:249-270`) is the right tool for agent tests and should
stay. **Gap:** `LangChainLLM` itself — `_messages()` cache-breakpoint layout (`llm.py:154-164`),
`_structured_model()` schema caching (`:166-171`), the `PARSE_RETRIES` ladder (`:206-224`) and `_record()` usage
accounting (`:173-187`) — has no test that runs without a key. `GenericFakeChatModel` + `with_structured_output` is
exactly the tool for that; `test_prompt_layout.py` only pins the pure `render_prompt`.

**Mermaid snapshot tests.** Measured, today, no changes needed:

```python
g = build_agent_graph(Agent(NoLLM()), None, "task", max_steps=5)     # session=None is fine: nodes are lazy
print(g.get_graph().draw_mermaid())
#   __start__ --> observe;
#   observe -.-> decide;  observe -.-> __end__;
#   decide  -.-> act;     decide  -.-> observe;  decide -.-> __end__;
#   act     -.-> observe; act     -.-> __end__;

o = build_orchestration_graph(GenerateRequest(task="t"), NoLLM())
print(o.get_graph().draw_mermaid())
#   __start__ --> explore;
#   explore -.-> verify;  explore -.-> generate;  explore -.-> __end__;
#   verify  -.-> explore; verify  -.-> generate;  verify  -.-> __end__;
#   generate -.-> validate; generate -.-> __end__;  validate -.-> __end__;
```

Both are derived from the `Command[Literal[...]]` return annotations, so a snapshot test on `draw_mermaid()`
**catches a node whose declared successors drift from its real `goto`s** — which is the actual failure mode. This is
the honest version of what was deleted in `70a3a3b` ("drop `agent_graph_mermaid` … a hand-mirrored copy of the
loop's structure") and `0a70be2`: generated from the graph, not mirrored by hand.
(`draw_mermaid` lives at `langchain_core/runnables/graph.py:577`; `CompiledStateGraph` exposes
`get_graph`/`aget_graph`/`get_subgraphs`/`aget_subgraphs`.)

**Verdict (e):** keep `FakeLLM`; add (1) a `draw_mermaid()` snapshot test for both graphs, (2) a `GenericFakeChatModel`
test for `LangChainLLM`'s structured-output retry ladder, (3) once the session moves to context, a graph-level test
that invokes the module-level explorer with a stub session — no browser, no key.

### (f) The Functional API for observe→decide→act

`@entrypoint`/`@task` would express our loop as a plain `while`:

```python
@entrypoint()
async def explore(inp: dict, runtime: Runtime[ExplorerContext]) -> AgentTrajectory:
    while n < budget:
        obs = await observe(...).result()
        dec = await decide(obs).result()
        if dec.done: break
        await act(dec).result()
```

Honest pros: the stuck-detection bookkeeping (`no_progress`, `prev_observation`, `prev_keys`, `prev_texts`,
`repeat_count`, `last_action_key` — six of `AgentState`'s fourteen fields, `graph.py:70-85`) is loop-local state that
only exists because the Graph API forces it into a channel dict. A `while` loop would keep them as locals. And
"@entrypoint and @tasks do not require explicit state management as their state is scoped to the function"
([functional-api](https://docs.langchain.com/oss/python/langgraph/functional-api)).

Cons, decisive for us:

1. **"The Functional API does not support visualization as the graph is dynamically generated during runtime."** We
   just deleted hand-written mermaid *specifically so the structure comes from the real graph* (`70a3a3b`,
   `0a70be2`). Adopting the Functional API would take that away permanently.
2. **Nobody upstream uses it.** Zero of the surveyed first-party templates, libraries or applications
   (`react-agent`, `new-langgraph-project`, `open_deep_research`, `deepagents`, `langgraph-swarm`,
   `langgraph-bigtool`, `langmem`) is `@entrypoint`-shaped. The `langgraph new` template list is
   `deep-agent-python`, `deep-agent-js`, `agent-python`, `new-langgraph-project-python`,
   `new-langgraph-project-js` — all Graph API.
3. **`@task` results must be serializable** for the checkpoint, and each `.result()` is a checkpoint write. Our
   per-step `DomSnapshot` is 160 bytes in the toy case but real ones are large; the Graph API lets us keep the
   snapshot in a channel we simply choose not to persist.
4. It does not solve (a). `@entrypoint(context_schema=...)` injects `runtime` the same way, so the resource problem
   is orthogonal.

**Verdict (f):** no. Stay on the Graph API. Revisit only if we ever want durable resumption *mid-step* with
`previous`-based memory, which is not on the roadmap.

---

## 4. The survey in one table

| Project | Agent is a class? | Resource injection | Cross-run memory | Config | Entry point |
|---|---|---|---|---|---|
| **`react-agent`** (template) | No — functions + `graph` | `Runtime.context` (`runtime.context.model`) | none (messages in state) | `@dataclass(kw_only=True) Context` + env fallback | module-level `graph`; `langgraph.json → graph.py:graph` |
| **`new-langgraph-project`** | No | `Runtime.context` (`TypedDict`) | none | `TypedDict Context` | module-level `graph` |
| **`langchain.agents.create_agent`** | No — factory → `CompiledStateGraph` | `context_schema=` + `store=` + `checkpointer=` | `store` / `checkpointer` | ctor kwargs + `AgentMiddleware` | return value of the factory |
| **`langgraph.prebuilt.create_react_agent`** | No — **deprecated** → `create_agent` | `context_schema=` | `store`/`checkpointer` | ctor kwargs | factory return |
| **`deepagents`** | No — `create_deep_agent()` → compiled graph | `context_schema=`, `backend=`, `store=` | `StateBackend` / `StoreBackend` / `CompositeBackend` | ~18 ctor kwargs + middleware | factory return; subagents via `CompiledSubAgent{"runnable": …}` + `await subagent.ainvoke(...)` |
| **`langgraph-swarm`** | No — `create_swarm()` → **uncompiled** `StateGraph` | caller compiles with store/ckpt | `SwarmState.active_agent` in state | ctor kwargs | caller's `.compile()` |
| **`langgraph-supervisor`** | **Deprecated** — "use the supervisor pattern directly via tools" | — | — | — | — |
| **`open_deep_research`** | No — 8 module functions, 3 compiled graphs | closure + `Configuration.from_runnable_config(config)` | state only | pydantic `Configuration` + `x_oap_ui_config` | `deep_researcher.py:deep_researcher`; children via `add_node(subgraph)` |
| **`langgraph-bigtool`** | No — `create_agent()` → **uncompiled** builder | **closure** over `llm`, `tool_registry`; `store` injected | `store` (tool embeddings) | ctor kwargs | caller's `.compile(store=…)` |
| **`langmem`** | No — 9 `create_*`; `ReflectionExecutor` is an overloaded factory | ctor args on `LocalReflectionExecutor` | `BaseStore` | ctor kwargs | factory return |
| **WebVoyager** (LangGraph tutorial, archived) | No | **live `Page` in graph state** | none | none | module-level `graph`; `graph.astream({"page": page, …})` |
| **`openbrowser-ai`** | **Yes** — `AgentGraphBuilder`, `self.graph = self._build_graph()`, nodes = bound methods | `self.agent.browser_session` | `self.agent.history` | `agent.settings` | `builder.run()` → `self.graph.ainvoke(...)` |
| **CopilotKit examples** | **Yes** — `class ItineraryAgent: self.graph = self._build_graph()` | `self.llm` | none | ctor | `self.graph` |
| **browser-use** | **Yes** — `class Agent(Generic[...])` (no LangGraph) | `self.browser_session` | `self.state` (`AgentState(BaseModel)`) | `AgentSettings(BaseModel)` | `agent.run()` |
| **Skyvern** | **Yes** — `ForgeAgent` (no LangGraph) | app singleton | DB | org settings | `agent.execute_step(...)` |
| **Magentic-UI** | **Yes** — `FaraWebSurfer` (no LangGraph) | `self._browser`, `self._context`, `__aenter__`/`__aexit__` | `_save_state()` | ctor | AutoGen `on_messages` |
| **Agno** | **Yes** — `@dataclass(init=False) class Agent` (no LangGraph) | ctor fields | ctor fields | ctor fields | `agent.run()` |
| **NetGent today** | **Yes** — `class Agent` | **closure**, graph rebuilt per `run()` | `Agent.history` (object attr) | ctor kwargs + `GenerateRequest` (orchestrator) | `agent.run(session, task, url)`; orchestrator factory |
| **NetGent proposed** | **No** for the loop; **yes** for `ExplorerMemory` | `Runtime.context` (`ExplorerContext`) | `ExplorerMemory` in context → swappable for `BaseStore` | `ExplorerContext` dataclass + `GenerateRequest` pydantic | module-level `EXPLORER`; `explore(...)` wrapper; orchestrator factory |

---

## 5. Recommendation

### 5.1 The rule to apply

From the survey, LangChain's implicit rule is sharp enough to state:

> **A class exists when it owns a live resource with a lifecycle. Everything graph-shaped is a function, and the
> unit of composition is a compiled graph.**

`langmem` is the proof: nine `create_*` functions, and the only genuine classes
(`LocalReflectionExecutor`, `RemoteReflectionExecutor`) own a thread, a priority queue and a lock.

By that rule, `Agent` (`explorer/agent.py:123-263`) is currently three unrelated things welded together:

| Responsibility | Lines | Rule says |
|---|---|---|
| **Per-run config** (`llm`, `max_steps`, `allowed_kinds`, `max_actions_per_step`, `run_dir`, `upload_file`) | `:124-151` | → `Runtime.context` |
| **Cross-run memory + a live `asyncio.Task`** (`history`, `noticed`, `_watch`, `note`, `drain_noticed`, `start_watch`, `stop_watch`) | `:153-195` | → **stays a class** |
| **The run driver** (build graph, `ainvoke`, assemble `AgentTrajectory`, write `trajectory.json`) | `:216-263` | → a function |

Splitting on those seams gets us LangGraph-idiomatic without giving up anything we use.

### 5.2 Refactor sketch

**`explorer/context.py`** (new; no langchain/langgraph import — safe for `agent/__init__.py`):

```python
"""What one exploration run needs. Passed as LangGraph `Runtime.context`, never checkpointed
(measured: context is not written to the checkpoint — docs/research/langgraph-agent-structure.md §3a)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, MAX_BATCH
from netgent.browser.session import BrowserSession

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


@dataclass(frozen=True, slots=True)
class ExplorerContext:
    # run dependencies — LangGraph's own words for this slot (langgraph/runtime.py:199-201)
    session: BrowserSession
    llm: "LLM"
    memory: "ExplorerMemory"
    task: str
    # knobs
    max_steps: int = 25
    frame_filter: list[str] | None = None
    allowed_kinds: frozenset[str] = DEFAULT_KINDS
    max_actions_per_step: int = 1
    run_dir: Path | None = None
    upload_file: Path | None = None

    def __post_init__(self) -> None:                       # was Agent.__init__ :137-146
        if not 1 <= self.max_actions_per_step <= MAX_BATCH:
            raise ValueError(f"max_actions_per_step must be 1..{MAX_BATCH}")
        unknown = self.allowed_kinds - ALL_KINDS
        if unknown:
            raise ValueError(f"unknown action kinds {sorted(unknown)}; choose from {sorted(ALL_KINDS)}")
```

**`explorer/memory.py`** (new; the one surviving class — the `LocalReflectionExecutor` rule):

```python
class ExplorerMemory:
    """Cross-run memory for ONE explorer working several tasks (a sweep), plus the settle
    watcher it owns. A class because it owns an asyncio.Task with a lifecycle — the same
    reason langmem's LocalReflectionExecutor is a class, and the same reason nothing here
    can move into graph state (state is per-run) or into a checkpoint (a Task will not
    serialize). Swap this for a BaseStore-backed implementation to run on LangGraph Platform;
    the three methods below are the whole interface."""

    def __init__(self) -> None:
        self.history: list[StepRecord] = []      # was Agent.history  (agent.py:153)
        self.noticed: list[str] = []             # was Agent.noticed  (agent.py:156)
        self._watch: asyncio.Task | None = None  # was Agent._watch   (agent.py:157)

    def note(self, text: str) -> None: ...       # verbatim from agent.py:172-195
    def drain_noticed(self) -> list[str]: ...    # verbatim from agent.py:168-170
    def start_watch(self, coro) -> None: ...     # verbatim from agent.py:159-161
    def stop_watch(self) -> None: ...            # verbatim from agent.py:163-166
```

**`explorer/graph.py`** — nodes stop being closures; the graph compiles once at import:

```python
from langgraph.graph import END, START, StateGraph      # module-level now: this module IS the langgraph one
from langgraph.runtime import Runtime
from langgraph.types import Command


async def observe(state: AgentState, runtime: Runtime[ExplorerContext]) -> Command[Literal["decide", "__end__"]]:
    ctx = runtime.context                    # NOTE: the kwarg MUST be named `runtime` (_runnable.py:230-243)
    n = state.get("n", 0) + 1
    if n > ctx.max_steps:
        return Command(update={"stopped_reason": f"reached max_steps={ctx.max_steps}"}, goto=END)
    snapshot = await ctx.session.snapshot()
    if ctx.frame_filter is not None:
        snapshot = snapshot.scoped_to(ctx.frame_filter)
    ...                                       # body otherwise unchanged from graph.py:106-158


async def decide(state, runtime: Runtime[ExplorerContext]) -> Command[Literal["act", "observe", "__end__"]]: ...
async def act(state, runtime: Runtime[ExplorerContext]) -> Command[Literal["observe", "__end__"]]: ...


EXPLORER = (                                  # compiled ONCE — Studio-visible, xray-visible, langgraph.json-able
    StateGraph(AgentState, context_schema=ExplorerContext)
    .add_node("observe", observe)
    .add_node("decide", decide)
    .add_node("act", act)
    .add_edge(START, "observe")
    .compile(name="explorer")
)


async def explore(
    session: BrowserSession,
    task: str,
    *,
    llm: "LLM",
    memory: ExplorerMemory | None = None,
    url: str | None = None,
    frame_filter: list[str] | None = None,
    max_steps: int = 25,
    run_dir: Path | None = None,
    allowed_kinds: frozenset[str] = DEFAULT_KINDS,
    max_actions_per_step: int = 1,
    upload_file: Path | None = None,
) -> AgentTrajectory:
    """The ONE run() API — for `netgent agent`, the sweep, the stress eval, and the
    orchestrator's explore node. Body is `Agent.run` (agent.py:216-263) unchanged except
    that the graph is no longer rebuilt: the per-run dependencies go in `context=`."""
    memory = memory or ExplorerMemory()
    traj = AgentTrajectory(task=task)
    dialog_mark = len(session.dialogs_seen())
    if url:
        await session.page.goto(url)
        traj.steps.append(AgentStep(n=0, kind="goto", reasoning="starting URL",
                                    url=session.page.url, action=GotoAction(url=url)))
    ctx = ExplorerContext(session=session, llm=llm, memory=memory, task=task, max_steps=max_steps,
                          frame_filter=frame_filter, allowed_kinds=allowed_kinds,
                          max_actions_per_step=max_actions_per_step, run_dir=run_dir,
                          upload_file=upload_file)
    final = await EXPLORER.ainvoke(
        {"steps": []}, config={"recursion_limit": 3 * max_steps + 8}, context=ctx,
    )
    ...                                       # trajectory assembly unchanged (agent.py:242-263)
    return traj
```

**`explorer/agent.py`** keeps only the models — `StepRecord`, `AgentStep`, `AgentTrajectory` and the constants
(`MAX_REPEAT`, `FOLD_MIN_STEPS`, `MAX_FOLDS`). The `class Agent` disappears. Two small helpers
(`capture_screenshot`, `upload_path` — `agent.py:197-214`) become module functions taking `ctx`.

**`orchestrator.py`** — keep the factory (see §5.4), change three lines in the `explore` node so it closes over the
module-level `EXPLORER` (which is what makes `get_subgraphs()`/xray work, §3d probe C→A):

```python
    async def explore(state: OrchestrationState) -> Command[Literal["verify", "generate", "__end__"]]:
        from netgent.agent.explorer.graph import explore as run_explorer   # closes over module-level EXPLORER
        from netgent.agent.explorer.decision import DEFAULT_KINDS
        ...
        async with BrowserSession(headless=req.headless) as session:
            traj = await run_explorer(
                session, task, llm=llm, url=req.url, run_dir=run_dir, max_steps=req.max_steps,
                allowed_kinds=DEFAULT_KINDS | set(req.allow_kinds),
                max_actions_per_step=req.max_actions_per_step,
            )
```

**`evals/sweep.py:121-131`** — the sweep is where the split pays off; `history` stops being a side effect of an
object we happen to reuse and becomes an explicit argument:

```python
    memory = ExplorerMemory()                                  # was: agent = Agent(llm, ...)
    for i, frame_path in enumerate(frame_paths):
        for attempt in range(retries + 1):
            memory.note(f"--- now working form {i + 1} of {len(frame_paths)} (attempt {attempt + 1}) ---")
            traj = await explore(session, FORM_TASK, llm=llm, memory=memory,
                                 frame_filter=frame_path, max_steps=budget,
                                 max_actions_per_step=max_actions_per_step, run_dir=run_dir)
```

### 5.3 What we keep, and why

| Keep | Why |
|---|---|
| **`ExplorerMemory` as a class** | Owns an `asyncio.Task` with `start_watch`/`stop_watch` and mutable cross-run state. This is exactly the case where LangChain itself writes a class (`langmem.LocalReflectionExecutor`). It also isolates the one thing that must change for LangGraph Platform (§3b). |
| **`StepRecord` / `AgentStep` / `AgentTrajectory` as pydantic models** | They are values; they round-trip through the checkpoint serializer (measured); the compiler reads them. Nothing to change. |
| **`GenerateRequest` as pydantic** | It is the CLI's flags model first. `context_schema` accepts pydantic (open_deep_research does it), so if we ever want a module-level orchestrator it can double as the context. |
| **The `LLM` Protocol seam (`llm.py:41-52`)** | It is what makes `FakeLLM` possible and keeps langchain lazy. It moves from `agent.llm` to `ctx.llm` — same object, better-declared. |
| **`Command`-routed nodes with `Literal` successor annotations** | They are what makes `draw_mermaid()` truthful (§3e). Also idiomatic — `langgraph-fundamentals/SKILL.md` documents `Command` for "node both updates state and picks the next node". |
| **The orchestrator as a hand-built `StateGraph`** | Already the right pattern ("Custom workflow" — [`langgraph-multi-agent.md`](langgraph-multi-agent.md) §4). Do not turn it into a supervisor/swarm; the compile order is fixed and known. |

### 5.4 What we deliberately do *not* do

- **Do not put the session in state** (WebVoyager's choice). It forecloses checkpointing permanently, and our state
  is already serializable — throwing that away for no gain would be a regression.
- **Do not `add_node(EXPLORER)` in the orchestrator.** `OrchestrationState` and `AgentState` share no keys, so the
  docs' wrapper-function form is required anyway, and the wrapper *is* what we already have. deepagents does the
  same (`await subagent.ainvoke(...)` inside the `task` tool).
- **Do not make the orchestrator graph module-level yet.** `agent/__init__.py` imports `orchestrator` at module
  level (`agent/__init__.py:10`) and promises "importing this package does not require the `netgent[generate]` extra"; a
  module-level compiled orchestrator would break that promise and the several unit tests that import
  `netgent.agent.*` without a key. `langgraph.json` supports factories (`./file.py:make_graph` taking
  `config: RunnableConfig`), so a thin adapter is enough if we ever deploy — no restructuring needed.
  `explorer/graph.py` is safe to make module-level because nothing in `agent/__init__.py` imports it; keep the
  re-export lazy (PEP 562 `__getattr__`) if `from netgent.agent import explore` is wanted.
- **Do not adopt the Functional API** (§3f) or Deep Agents for the orchestrator (already settled in
  [`langgraph-multi-agent.md`](langgraph-multi-agent.md) §6).

### 5.5 What this buys, concretely

1. **One compile instead of one per run** — and `EXPLORER` is a real module-level object, so
   `get_subgraphs()`/`get_graph(xray=True)`/Studio see the explorer nested inside the orchestrator (§3d probe A vs C).
2. **A checkpointer becomes a one-line option** (`EXPLORER = ....compile(checkpointer=…)`) because state is already
   serializable and context is never serialized (§3a).
3. **Graph-level tests without a browser** — `EXPLORER.ainvoke({"steps": []}, context=ExplorerContext(session=stub,
   llm=FakeLLM(script), …))` — matching `react-agent`'s `test_graph.py` shape.
4. **A `draw_mermaid()` snapshot test** that catches successor-annotation drift — the honest replacement for what
   `70a3a3b`/`0a70be2` deleted.
5. **The Platform migration is scoped to one class.** `ExplorerMemory` is the only process-bound thing left.

### 5.6 Suggested order (each step is independently shippable and testable)

1. Add `ExplorerMemory` (move `history`/`noticed`/`_watch`/`note`/`drain_noticed`/`start_watch`/`stop_watch`
   verbatim). `Agent` delegates to it. Tests (`test_agent_memory.py:48-70`) change only in how they construct it.
2. Add `ExplorerContext`; `build_agent_graph` builds one internally and nodes read `ctx.` instead of the closed-over
   names. No behaviour change; the `Runtime` plumbing is not in yet.
3. Switch nodes to `(state, runtime: Runtime[ExplorerContext])`, hoist `EXPLORER` to module level, add
   `explore(...)`. **Watch the kwarg name** — it must be `runtime` (`_runnable.py:230-243`).
4. Point `cli/agent_command.py:46-49`, `evals/sweep.py:121-131`, `evals/stress.py:80-84` and
   `orchestrator.py:106-127` at `explore(...)`; delete `class Agent`.
5. Add the two tests from §3e (mermaid snapshot; `GenericFakeChatModel` cover for `LangChainLLM`'s retry ladder).
6. *Optional, later:* `compile(checkpointer=…)`, `allowed_msgpack_modules` registration, and a
   `make_graph(config)` adapter for `langgraph.json`.

---

## 6. Cross-references

- [`langgraph-multi-agent.md`](langgraph-multi-agent.md) — **which** multi-agent pattern (answer: Custom workflow;
  supervisor/swarm/handoffs put an LLM in the routing decision, which a compiler must not do). Also `Send` fan-out
  for `--runs N`, which is still unimplemented and is a better use of a refactor than anything here.
- [`browser-agent-architectures.md`](browser-agent-architectures.md) — role decomposition; why browser-use deleted
  its planner agent.
- [`browser-agent-memory.md`](browser-agent-memory.md) §6.2 — the `StepRecord`/fold design that `ExplorerMemory`
  inherits unchanged.
- [`explorer-optimisation.md`](explorer-optimisation.md) §2 — the A/B numbers behind the `NETGENT_OBS_DIFF` /
  `NETGENT_MEMORY_FIELDS` defaults; none of them are affected by this refactor.

---

## 7. Unverified / could not confirm

1. **`langchain-ai/langgraph/discussions/4390` ("Prebuilt Agents in LangGraph: Classes or Functions?")** — a web
   search surfaced this with a summary (arguments for functions: "if prebuilts are meaningfully reliant on
   implementation details of other prebuilts, it's a code smell … prebuilts should instead be built via
   composition"; arguments for classes: `create_react_agent`'s extensibility limits; and a note that the functional
   and StateGraph APIs are "two ways to access the same underlying orchestration engine … largely a matter of
   personal preference"). **I could not verify any of it**: GitHub Discussions are disabled on the repo as of
   2026-08-28 (`hasDiscussionsEnabled: false`, `discussions.totalCount: 0` via GraphQL), the URL 404s over both
   WebFetch and `gh api`, and a discussion search returns nothing. Treat the quoted phrasings as second-hand. The
   *conclusions* in this doc do not rest on it — §2.4 derives the same position from shipped, verifiable code.
2. **`langgraph#5700` "Runtime context is not being passed to the subgraph"** — I did not read the thread; I only
   measured that context *does* propagate in 1.2.11 (§3d). Whether it was a bug, a version difference, or a
   different configuration, I don't know.
3. **Stagehand's `Agent`** — `repo:browserbase/stagehand "class Agent"` and a `lib/v3` path search both returned 0
   hits; I did not locate the file. The claim "Stagehand's agent is a class" is **unverified** here. (Stagehand's
   `%var%` parameter contract, cited elsewhere in our prompt, comes from
   [`browser-agent-prompting.md`](browser-agent-prompting.md), not from this survey.)
4. **Magentic-UI `WebSurfer`** — the class I found and cite is `FaraWebSurfer`
   (`src/magentic_ui/agents/web_surfer/fara/_fara_web_surfer.py`, 984 lines, `__init__` at :66). Whether an older
   `WebSurfer` class still exists elsewhere in that repo, I did not check; `"class WebSurfer"` returned 0 hits.
5. **`langgraph.json` factory return type** — the docs say the factory returns "an instance of
   `langgraph.graph.state.StateGraph`" while the CLI skill's table says "a `CompiledGraph` or a function returning
   one". I did not test the dev server, so whether a factory may return a *compiled* graph is unconfirmed. Test
   before relying on it.
6. **`docs/docs/tutorials/*` in `langchain-ai/langgraph`** — the path no longer exists on `main`; the customer
   support / SQL agent / plan-and-execute / reflection / self-RAG tutorials were read only as archived stubs plus
   the one pinned WebVoyager notebook (`23961cff61a4`). Their current form lives on `docs.langchain.com` and I did
   not re-survey them there; conclusions about "LangGraph tutorials use functions" rest on the archived stubs and
   on `open_deep_research`/templates, not on the live tutorial pages.
7. **`deepagents` HEAD SHA** — `a1af029e6e73cb17c36bff823d227747b28e91e1` is the ref the GitHub contents API
   returned when I listed the repo root; I did not separately confirm it is the tip of `main` at a stated time.
8. **Third-party class-usage counts** (108 / 90 files) are GitHub code-search totals on 2026-08-28. Code search
   indexes a subset of GitHub and the number is not a census.
9. **The `openbrowser-ai` excerpt** was read through a summarising fetch, not line-by-line; the quoted
   `_build_graph`, `GraphState` and `run` bodies are faithful in structure but I did not verify exact line numbers.
