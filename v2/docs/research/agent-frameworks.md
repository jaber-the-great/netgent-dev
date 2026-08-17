# Agent Frameworks & Orchestration Stacks in Open-Source Browser Agents

**Status:** primary-source survey · **Date:** 2026-08-17 · **Scope:** 15 open-source browser/web agent
projects, verified against dependency manifests and agent-loop source at the commits listed in §1.

**Method.** Every claim below was verified by reading the actual manifest (`pyproject.toml`,
`package.json`, `requirements.txt`, `pnpm-workspace.yaml`) and the actual agent-loop source in a
`git clone --depth 1` of each repo, plus `gh api` for history (tagged manifests, commit search, PR
bodies, release notes). Nothing was taken from the prior batch docs
([`browser-agents-batch-1..7.md`](browser-agents-batch-1.md)) without re-verification; three of their
claims turned out to be stale and are corrected in §3 (Stagehand's LLM layer, browser-use's provider
count, DeepResearch's qwen-agent dependence).

Companion docs: [`browser-agents.md`](../browser-agents.md) (feature-level survey),
[`browser-layer-design.md`](../browser-layer-design.md) (browser layer), [`OVERVIEW.md`](../OVERVIEW.md)
(NetGent v2 architecture).

---

## 1. Repos surveyed, at the commit verified

| Repo | Verified commit / date | ★ | Lang | Last push | Created |
|---|---|---|---|---|---|
| browser-use/browser-use | `3c989dc` 2026-08-17 | 109.5k | Python | 2026-08-17 | 2024-10-31 |
| Skyvern-AI/skyvern | `ef7b59b` 2026-08-15 | 22.8k | Python | 2026-08-17 | 2024-02-28 |
| browserbase/stagehand | `0af36da` 2026-08-14 | 24.0k | TypeScript | 2026-08-17 | 2024-03-24 |
| lavague-ai/LaVague | `9024bb8` 2025-01-21 | 6.4k | Python | 2025-01-21 (dead) | 2024-02-26 |
| OSU-NLP-Group/SeeAct | 2025-02-02 | 850 | Python | 2025-02-03 (dormant) | 2023-12-21 |
| MinorJerry/WebVoyager | 2024-03-04 | 1.1k | Python | 2024-03-04 (frozen) | 2024-01-24 |
| EmergenceAI/Agent-E | 2025-05-12 | 1.2k | Python | 2026-05-04 | 2024-03-28 |
| nanobrowser/nanobrowser | 2025-11-24 | 13.6k | TypeScript | 2025-11-24 | 2024-12-31 |
| nottelabs/notte | 2026-08-14 | 2.0k | Python | 2026-08-17 | 2024-12-08 |
| bytedance/UI-TARS-desktop | 2026-07-01 | 38.6k | TypeScript | 2026-08-05 | 2025-01-19 |
| Alibaba-NLP/DeepResearch | 2026-02-27 | 19.8k | Python | 2026-02-27 | 2025-01-09 |
| steel-dev/surf.new | 2025-05-22 | 512 | TypeScript | 2025-07-17 | 2025-01-30 |
| microsoft/Webwright | 2026-08-03 | 5.9k | Python | 2026-08-03 | 2026-04-08 |
| omxyz/lumen | 2026-03-29 | 56 | TypeScript | 2026-03-30 | 2026-03-01 |
| browserable/browserable | 2025-08-27 | 1.2k | JavaScript | 2025-08-27 | 2025-04-07 |

★ = stars at time of survey (`gh api repos/<r> --jq .stargazers_count`).

---

## 2. Master table

| Repo | Agent orchestration | LLM client layer | Providers | Structured output | Multi-agent structure |
|---|---|---|---|---|---|
| **browser-use** | Custom loop — `Agent` class, `browser_use/agent/service.py:133`; `run()` at `:2506` → `_execute_step()` `:2441` → `step()` `:1029` | **Own** `browser_use/llm/` abstraction: `BaseChatModel` Protocol (`llm/base.py:18`), one adapter dir per provider | 15 adapter dirs (`anthropic aws azure browser_use cerebras deepseek google groq litellm mistral oci_raw ollama openai openrouter vercel`) — incl. a **litellm passthrough** and a **LangChain escape hatch** (`ChatLangchain`, unsupported) | **JSON-schema forcing** on a pydantic model: `output_format=self.AgentOutput` (`service.py:1946`) → `ResponseFormatJSONSchema` (`llm/openai/chat.py:256`), with `add_schema_to_system_prompt` fallback (`:43`) and `model_validate_json` (`:301`). Not native tool-calling | Single loop; plan is a **field of the main output** (`plan_update`, `agent/views.py:396`) not a separate agent; optional **LLM judge** post-hoc (`use_judge`, `service.py:184`; `_judge_trace()` `:1587`; `agent/judge.py`) |
| **Skyvern** | Custom loop — `ForgeAgent` (`skyvern/forge/agent.py:565`, 7,301 LOC), `execute_step()` `:1048`, `agent_step()` `:1789`. Newer `taskv3` path: `run_agent_tool_loop()` (`forge/taskv3/loop.py:181`, `while outcome is None` `:217`). **Copilot** subsystem on **OpenAI Agents SDK** (`openai-agents>=0.10.5,<0.15`; `Runner.run_streamed` `forge/sdk/copilot/enforcement.py:1181`) | **litellm** + `litellm.Router` (`forge/sdk/api/llm/api_handler_factory.py:906,932`, `acompletion` `:1852`) | 17 `ENABLE_*` provider families (`skyvern/config.py`: anthropic, azure, azure-cua, bedrock, gemini, groq, inception, moonshot, novita, ollama, openai, openai-compatible, openrouter, vertex-ai, volcengine, xai, yutori); **~289 registered model configs** in `config_registry.py` | **Hybrid.** Legacy path: prompt-and-parse with `json_repair.loads` (`llm/utils.py:292`, `:449`) + `commentjson` + `schema_validator.py`. taskv3 path: **native OpenAI function calling** (`ToolSpec.to_openai_tool()` `taskv3/loop.py:58`) | Many LLM roles, one process: ~90 Jinja prompt templates in `forge/prompts/skyvern/` incl. `check-user-goal`, `decisive-criterion-validate`, `quality-audit`, `page-classify`, `check-evaluation-goal`. Separate CUA callers (`ui_tars_llm_caller.py`, `yutori_navigator_llm_caller.py`). Copilot = guardrailed OpenAI-Agents-SDK agent |
| **Stagehand (v4)** | **None client-side.** `Stagehand` is a JSON-RPC client (`packages/sdk-ts/src/stagehand.ts:63`, `rpcClient` `:65`); `act/observe/extract` are RPC calls (`:206,222,243`). The loop moved **server-side** (closed source) | **None client-side.** Client deps are `@browserbasehq/sdk`, otel, `chrome-launcher`, `zod` (`packages/sdk-ts/package.json:44-50`). Optional **client-side LLM callback** via `ClientLLMSchema` (`src/clientSchemas.ts:134`) + `removeClientLLMHandler` (`stagehand.ts:178`) | 0 in client. v3 client had `openai`, `@anthropic-ai/sdk`, `@google/genai`, **`ai@^5` (Vercel AI SDK)** + `@ai-sdk/provider` — verified at tag `stagehand-server-v3/v3.7.4` | **zod** (`zod@4.4.3` in `pnpm-workspace.yaml` catalog) for schemas over the wire; forcing happens server-side | Server-side. Client ships **integration examples** wiring Stagehand-as-tools into 8 *other* frameworks: `claude-code` (`@anthropic-ai/claude-agent-sdk`), `codex` (`@openai/codex-sdk`), `crewai`, `deepagents`, `eve`, `mastra` (`@mastra/core`), `pi`, `vercel-ai` (`ai@^7`) — all under `packages/integrations/`, all MCP-mediated |
| **LaVague** (dead) | Custom loop — `WebAgent` (`lavague-core/lavague/core/agents.py:42`), `for curr_step in range(n_steps)` `:243`, also `:512` | **llama-index** — `llama-index = "0.10.56"` pinned (`lavague-core/pyproject.toml:28`). LLMs typed as `llama_index.core.base.llms.base.BaseLLM`; embeddings as `BaseEmbedding`; `BM25Retriever` for DOM-chunk RAG (`retrievers.py`). **LangChain present for exactly one import**: `RecursiveCharacterTextSplitter` (`retrievers.py:8`) | 5 "context" packages (openai + azure-openai, anthropic, gemini, fireworks) + cohere reranker — each a bundle of `llama-index-llms-*` / `-embeddings-*` / `-multi-modal-llms-*` | **Raw text parsing.** `extractors.py`: `YamlFromMarkdownExtractor`, `JsonFromMarkdownExtractor`, `PythonFromMarkdownExtractor`, `DynamicExtractor` (`:43,79,117,161`). No function calling, no schema forcing | Planner + specialised engines: `WorldModel` (planner) → `ActionEngine` (dispatcher) → `NavigationEngine` / `PythonEngine` / `NavigationControl`; `evaluator.py` for offline scoring |
| **SeeAct** (dormant) | Custom loop — `SeeActAgent` (`seeact_package/seeact/agent.py:36`); two-stage `predict()` `:585` then `execute()` `:755`; driver loop `while not complete_flag` (`src/seeact.py:279`) | **litellm** — `litellm==1.35.32` pinned (`seeact_package/pyproject.toml:28`); `engine_factory()` (`demo_utils/inference_engine.py:54`) → `litellm.completion` (`:208,263,302`) | 3 engines: `OpenAIEngine`, `GeminiEngine`, `OllamaEngine` (+ `OpenaiEngine_MindAct` for the offline benchmark) | **Raw text parsing.** Two-stage prompt: free-form action generation, then multi-choice grounding (`ACTION: Choose an action from {…}`, `agent.py:300`), parsed by string matching | Single agent, two-stage prompting. No planner/validator agents |
| **WebVoyager** (frozen) | Custom loop — single file `run.py`; `while it < args.max_iter` (`:321`) | **Native OpenAI SDK only** — `openai==1.1.1` (`requirements.txt`); `OpenAI()` at `run.py:257`, `call_gpt4v_api()` `:117` | 1 (OpenAI GPT-4V) | **Regex parsing** — `extract_information()` (`utils.py:213-233`) matches `Click [N]`, `Type [N]; [text]`, `Scroll`, `ANSWER; [..]` | Single agent. Total deps: `openai`, `selenium`, `pillow` |
| **Agent-E** | **Framework: AutoGen / AG2** — `autogen~=0.7` (`pyproject.toml:22-24`). `AutogenWrapper` (`ae/core/autogen_wrapper.py:29`) builds `ConversableAgent`s, wires `register_nested_chats()` `:149`, drives via `a_initiate_chat()` `:368` | **AutoGen's own** `llm_config={"config_list": …}` (`ae/core/agents/browser_nav_agent.py:59-61`); config from `AUTOGEN_MODEL_*` env or per-agent JSON (`ae/core/agents_llm_config.py:14-18`) | OpenAI / Azure / Anthropic / Groq via AG2 extras, plus any OpenAI-compatible `base_url` (LiteLLM+Ollama documented) | **AutoGen function calling** — `agent.register_for_llm(description=…)(fn)` + `browser_nav_executor.register_for_execution()(fn)`, ~20 skills (`browser_nav_agent.py:82-100`) | **Planner + browser-nav, as an AG2 nested chat.** `high_level_planner_agent.py` + `browser_nav_agent.py` + `UserProxyAgent_SequentialFunctionExecution` executor; `trigger_nested_chat()` (`autogen_wrapper.py:103`) |
| **nanobrowser** | Custom loop — `Executor` (`chrome-extension/src/background/agent/executor.ts:38`); `for (let step …)` `:150`; alternates `runPlanner()` `:158` and `navigate()` `:167` on `planningInterval` | **Framework: LangChain.js** chat models — 9 `@langchain/*` packages (`chrome-extension/package.json`) | 8 providers via LangChain.js (`anthropic cerebras deepseek google-genai groq ollama openai xai`) + OpenAI-compatible custom endpoints | **LangChain `withStructuredOutput`** on a zod schema (`agents/base.ts:130`) with `zod-to-json-schema` + a **per-model capability gate** `setWithStructuredOutput()` (`:107`; disabled for `deepseek-reasoner`/`r1` and Llama API) and `jsonrepair` fallback | **Planner + Navigator.** Historically also a Validator — **deleted 2025-08-22**, PR [#204](https://github.com/nanobrowser/nanobrowser/pull/204) "Remove validator agent and transfer responsibilities to planner" (commit `19d7a82`) |
| **notte** | Custom loop — `NotteAgent` (`packages/notte-agent/src/notte_agent/agent.py:49`); `while self.trajectory.num_steps < self.config.max_steps` `:401`; `step()` `:144`. Subclasses `FalcoAgent` (`falco/agent.py:15`), `WorkflowAgent` (`workflow.py:14`) | **litellm** + **llamux** router — `litellm>=1.74.12`, `llamux>=0.1.9`, `json-repair>=0.57.1` (`packages/notte-llm/pyproject.toml:16-19`); `LLMEngine` (`notte_llm/engine.py`), `Router.from_csv` (`service.py:44`) | litellm's full matrix; llamux load-balances across a CSV-declared model pool | **pydantic `response_format` with per-provider schema surgery** — `fix_schema_for_openai()` / `fix_schema_for_gemini()` / native Anthropic (`engine.py:369-395`), degrading to `{"type":"json_object"}` then `repair_json` | **Agent + LLM-as-judge validator.** `CompletionValidator` (`common/validator.py:39`) gates every `CompletionAction`; agent and validator must **agree** to stop (`agent.py:211-229`). Also validates the user's `response_format` (`validator.py:83`) |
| **UI-TARS-desktop / Agent TARS** | **Own framework: `@tarko/*`** (21 packages under `multimodal/tarko/`). `LoopExecutor` (`tarko/agent/src/agent/runner/loop-executor.ts:19`), `for (let iteration = 1; iteration < this.maxIterations; …)` `:63`. `@tarko/mcp-agent` → `@agent-tars/core` | **`@tarko/llm-client`** — a **fork of [token.js](https://github.com/token-js/token.js)**; reason documented in `tarko/llm-client/README.md:7`: *"For multimodal and Azure OpenAI support, we had to fork."* Bundles native SDKs: `@anthropic-ai/sdk`, `@google/generative-ai`, `@mistralai/mistralai`, `openai@4.93.0` | token.js's native set (openai/anthropic/google/mistral/…) + 4 OpenAI-compatible high-level providers declared in `model-provider/src/constants.ts:12-34` (`ollama`, `lm-studio`, `volcengine`, `deepseek`) + `openrouter`, `azure-openai`, `openai-compatible` (`llm-client.ts:12`) | **All three, selectable per model** — `tool-call-engine/`: `NativeToolCallEngine.ts` (function calling), `StructuredOutputsToolCallEngine.ts` (JSON schema), `PromptEngineeringToolCallEngine.ts` (raw text). Plus `jsonrepair@3.12.0` + `zod-to-json-schema` (`tarko/agent/package.json`) | **Composable plugin fleet.** `ComposableAgent extends Agent` + `AgentComposer` over `AgentPlugin[]` (`omni-tars/core/src/{ComposableAgent,AgentComposer,AgentPlugin}.ts`); `OmniTARSAgent extends ComposableAgent` (`omni-agent/src/index.ts:11`) composing `code-agent` + `gui-agent` + `mcp-agent` |
| **Alibaba DeepResearch** | **Custom loop inside a framework shell.** `MultiTurnReactAgent(FnCallAgent)` subclasses `qwen_agent.agents.fncall_agent` (`inference/react_agent.py:10,47`) but overrides the loop entirely: `while num_llm_calls_available > 0` `:138`, calling a raw `OpenAI()` client against a local vLLM port (`call_server()` `:59`, client `:64`). **Newer subprojects dropped qwen-agent outright** | `qwen-agent==0.0.26` (`requirements.txt:138`) for message schema/tool base only; **actual inference via `openai`/`AsyncOpenAI` against a self-hosted vLLM 0.10.1 endpoint**. `NestBrowse`, `ParallelMuse`, `AgentFold` import only `AsyncOpenAI`/`OpenAI` + `mcp` — zero qwen-agent | 1 effective (OpenAI-compatible → own vLLM server) | **Raw text parsing** of XML-ish tags: `<tool_call>…</tool_call>` split then `json5.loads` (`react_agent.py:159-172`), `<answer>` sentinel `:181`. No schema forcing | Per-paper variants: `WebDancer`/`WebSailor`/`WebWatcher`/`WebWeaver` use qwen-agent `Assistant`/`MultiAgentHub`; `ParallelMuse` does **parallel rollout + aggregation** (`functionality_specified_partial_rollout.py`, `compressed_reasoning_aggregation.py`); `AgentFold` uses a `ThreadPoolExecutor` fleet; `NestBrowse` nests sub-agents over MCP |
| **steel-dev/surf.new** | Custom loop — `base_agent()` (`api/plugins/base/agent.py:12`), `while True:` `:31` over `llm.bind_tools(tools).astream(...)` `:39`. **No LangGraph** despite the docstring's "We can use a LangChain agent" `:22` | **LangChain chat models** (`api/providers.py:3-14`, `create_llm()` `:54`). Frontend streams in **Vercel AI SDK** wire format (`ai@4.0.30`, `@ai-sdk/ui-utils@1.0.7` in `package.json`) | 6 used in `providers.py` (openai, azure-openai, anthropic, anthropic-beta/CUA, google-genai, ollama, + custom base-URL OpenAI). `requirements.txt` additionally pins `langchain-aws`, `langchain-fireworks` — **inherited from `browser-use==0.1.30`'s dependency tree**, not used by surf.new's own code | **LangChain `bind_tools` → `tool_calls`** (`base/agent.py:63-67`), i.e. native function calling via LangChain's normalisation | 3 swappable "plugins", each its own loop: `plugins/base` (generic tool loop), `plugins/claude_computer_use`, `plugins/browser_use` (embeds `browser-use==0.1.30` as a library) |
| **microsoft/Webwright** | Custom loop — `DefaultAgent` (`src/webwright/agents/default.py:83`), `run()` `:341` with `while True:` `:363` → `step()` `:383` → `query()` `:386` → `execute_actions()` `:400` | **Own thin `Model` base over raw `httpx`** (`src/webwright/models/base.py:12,225`). **No provider SDK at all** — total runtime deps are `httpx, jinja2, pydantic, pyyaml, rich, typer, playwright, python-dotenv, platformdirs` (`pyproject.toml:9-19`) | 3 subclasses hitting REST endpoints directly: `openai_model.py` (`/v1/responses`, `:108`), `anthropic_model.py` (`/v1/messages`, `:139`), `openrouter_model.py`; any custom endpoint via config | **JSON-schema forcing, hand-rolled.** `_response_schema()` returns the schema (`models/base.py:307-319`); OpenAI adapter sends `{"text":{"format":{"type":"json_schema","strict":True}}}` (`openai_model.py:133-138`); `parse_json_output()` (`base.py:107`) validates | Single agent loop + a **compile-time `skill_factory` pipeline** (see §4.3): `route → build → learn → gate → decide → retrieve → fill → execute → update`, with `--verify {off,shape,strict}` and `--verify-rounds` (`skill_factory/learn.py:223,318,323`) |
| **omxyz/lumen** | Custom loop — `PerceptionLoop.run()`, `for (let step = 0; step < options.maxSteps; step++)` (`src/loop/perception.ts:173`); `Agent` façade `src/agent.ts:185` | **Native provider SDKs behind own `ModelAdapter`** (`src/model/adapter.ts:54`): `@anthropic-ai/sdk@^0.39`, `@google/genai@^1.3`, `openai@^4.96` + `src/model/custom.ts`. No framework, **no zod** | 3 native (anthropic, openai, google) + custom adapter | **Native CUA tool-use blocks, decoded by hand.** `ActionDecoder` (`src/model/decoder.ts:4`) maps Anthropic `tool_use` (`:5`, `computer_20250124` schema `:69`) and Google `function_call` (`:78`, denormalising 0-1000 coords) into a closed `Action` union | Rich, all in-process: `loop/planner.ts`, `loop/verifier.ts` (`UrlMatchesGate`, `CustomGate`, **`ModelVerifier`** `:45`), `loop/action-verifier.ts`, `loop/confidence-gate.ts`, `loop/router.ts`, `loop/child.ts` (`ChildLoop` `:17` — sub-agent delegation), `loop/repeat-detector.ts`, `loop/checkpoint.ts` |
| **browserable** | Custom loop, **distributed as queue jobs** — no in-process for-loop. Steps are Bull jobs: `agentQueue.process("jarvis-queue-job", 4, …)` (`tasks/agents/jarvis.js:3655`), `flowQueue.process("create-run", …)` `:3799` | **Own hand-rolled OpenAI-compatible router** — `services/llm.js`: `callOpenAICompatibleLLMWithRetry()` `:39` → `callOpenAICompatibleLLM()` `:171` over a literal model table `:184` with per-model capability flags (`supportedJsonSchema`, `supportedJsonOutput`, `supportedImageAs`), via **axios** `:1`. `openai` npm dep is used only for the zod helper | 9 models across 5 endpoints (openai, gemini via OpenAI-compat, deepseek ×2, qwen-plus via DashScope, claude-3-5-sonnet/haiku) | **zod + `zodResponseFormat`** from `openai/helpers/zod` (`agents/jarvis.js:7-8`), gated by the per-model `supportedJsonSchema` flag; hand-written parameter schemas in `agents/base.js` | **Runner + agent fleet.** `jarvis.js` (4,438 LOC) is the planner/runner dispatching to `BrowserableAgent` (7,295 LOC), `DeepResearchAgent`, `GenerativeAgent` (`jarvis.js:2-4,45-47`) over the queue |

---

## 3. Distribution analysis

### 3.1 Headline count

Of 15 projects, **3 use a general-purpose agent framework for orchestration**:

| Uses a framework for the loop | Framework |
|---|---|
| EmergenceAI/Agent-E | AutoGen / AG2 (`autogen~=0.7`) — nested chats, `a_initiate_chat` |
| Skyvern (Copilot subsystem only) | OpenAI Agents SDK (`Runner.run_streamed`) — the *main* browser loop is custom |
| Alibaba DeepResearch (older subprojects) | qwen-agent `Assistant` / `MultiAgentHub` — the *flagship* `react_agent.py` overrides the loop |

**12 of 15 write their own loop.** Counting strictly (framework drives the control flow of the
primary browser agent): **1 of 15** — Agent-E. Every other project's main loop is a hand-written
`for`/`while` over "build messages → call model → parse → execute → append".

### 3.2 The loop and the LLM client are separate decisions

This is the most useful distinction in the data. "Uses LangChain" almost never means "uses LangChain
for orchestration" — it means "uses `langchain_*` as a provider-normalisation shim."

| LLM client layer | Projects | n |
|---|---|---|
| **Own abstraction over native SDKs** | browser-use (`llm/base.py`), Stagehand v1–v3 (`LLMClient`), UI-TARS (`@tarko/llm-client`, token.js fork), lumen (`ModelAdapter`), Webwright (`Model` over httpx), browserable (`services/llm.js` over axios) | 6 |
| **litellm** | Skyvern (+`litellm.Router`), notte (+llamux), SeeAct | 3 |
| **LangChain / LangChain.js chat models** | nanobrowser, surf.new | 2 |
| **llama-index** | LaVague | 1 |
| **Framework-native config** | Agent-E (AutoGen `config_list`) | 1 |
| **Single native SDK** | WebVoyager (`openai`), DeepResearch (`openai` → own vLLM) | 2 |
| **None (server-side)** | Stagehand v4 | 1 |

So: **6 roll their own client, 3 use litellm, only 2 use LangChain chat models, 1 uses llama-index.**
Both LangChain users are TypeScript/Python web apps where LangChain.js/`langchain_*` is the cheapest
way to get 8 providers behind one `.invoke()`; neither uses LangGraph, `AgentExecutor`, chains, or
memory.

### 3.3 Structured output

| Mechanism | Projects | n |
|---|---|---|
| **JSON-schema forcing on a pydantic/zod model** | browser-use, notte, nanobrowser, Webwright, browserable, UI-TARS (`StructuredOutputsToolCallEngine`) | 6 |
| **Native function/tool calling** | Agent-E, surf.new, Skyvern (taskv3), UI-TARS (`NativeToolCallEngine`), lumen (CUA `tool_use`) | 5 |
| **Raw text / regex / tag parsing** | WebVoyager, SeeAct, LaVague, DeepResearch, UI-TARS (`PromptEngineeringToolCallEngine`), Skyvern (legacy) | 6 |

Two patterns recur in every mature project and are worth copying verbatim:

1. **A repair step is mandatory, not optional.** `json_repair` (Skyvern `llm/utils.py:292`, notte
   `engine.py:9`), `jsonrepair` (UI-TARS `agent/package.json`, nanobrowser `chrome-extension/package.json`),
   `json5.loads` (DeepResearch `react_agent.py:167`), `json-repair` (notte). Six of fifteen ship a
   JSON repairer in production deps. Nobody trusts `json.loads` on model output.
2. **Schema forcing is capability-gated per model, with a documented degradation ladder.**
   nanobrowser `setWithStructuredOutput()` (`agents/base.ts:107`) disables it for
   `deepseek-reasoner`/`r1`/Llama-API; notte rewrites the schema per provider then falls back
   `json_schema → json_object → repair_json` (`engine.py:369-408`); browser-use has
   `add_schema_to_system_prompt` (`llm/openai/chat.py:43`) and strips unsupported JSON-Schema
   keywords for Mistral (`llm/README.md`); browserable carries `supportedJsonSchema` /
   `supportedJsonOutput` booleans per model (`services/llm.js:184+`). **UI-TARS generalises this into
   three interchangeable tool-call engines** — the cleanest design in the survey.

### 3.4 Multi-agent structure

| Shape | Projects |
|---|---|
| Single loop | WebVoyager, SeeAct, Webwright (run side), Stagehand (client) |
| Single loop + judge/validator | browser-use (optional judge), notte (mandatory agree-to-stop validator), lumen (`ModelVerifier` + `ConfidenceGate` + `ActionVerifier`) |
| Planner + Navigator | nanobrowser, Agent-E, LaVague (WorldModel + engines) |
| Fleet / composed | UI-TARS (`ComposableAgent` plugins), browserable (Jarvis + 3 agents over a queue), DeepResearch (ParallelMuse parallel rollout, AgentFold thread pool), Skyvern (~90 prompt roles + CUA callers + Copilot) |

**Direction of travel is toward fewer agents, not more.** nanobrowser deleted its Validator agent and
folded the job into the Planner (PR #204, 2025-08-22). browser-use never had a separate planner — the
plan is a field on the single output schema (`agent/views.py:396`). notte kept its validator but made
it a *function* (`CompletionValidator`), not an agent with its own loop. The fleets that survive
(UI-TARS, browserable, DeepResearch) are fleets of *specialists* over different tool surfaces, not
planner/critic/executor role-play.

### 3.5 Correlation with maturity

Sorting by stars and by "is it still being pushed":

| Tier | Projects | Orchestration |
|---|---|---|
| >20k ★, actively pushed | browser-use (109k), UI-TARS (39k), Stagehand (24k), Skyvern (23k), DeepResearch (20k) | **5/5 custom loop** (one own-framework); **0/5 on a third-party agent framework** for the primary loop |
| 1k–20k ★ | nanobrowser (13.6k), Webwright (5.9k), LaVague (6.4k, dead), notte (2.0k), browserable (1.2k), Agent-E (1.2k), WebVoyager (1.1k) | 6/7 custom; **the one framework-orchestrated project (Agent-E) and the one llama-index project (LaVague) are the two least-maintained in the tier** |
| <1k ★ | SeeAct (850), surf.new (512), lumen (56) | 3/3 custom |

Three signals:

- **Every project above 20k stars writes its own loop and its own (or litellm-mediated) client
  layer.** There is no counterexample in the survey.
- **Framework adoption correlates with abandonment, and the causal arrow is legible.** LaVague pinned
  `llama-index = "0.10.56"` exactly (`lavague-core/pyproject.toml:28`) and its provider bundles pinned
  `llama-index-llms-anthropic = "0.1.15"`, `llama-index-llms-azure-openai = "0.1.10"` — pins from
  mid-2024, on a library that shipped 0.11/0.12 breaking changes shortly after. Last commit
  2025-01-21. Agent-E pins `autogen~=0.7` on a package (`autogen` → AG2) that itself forked out from
  under Microsoft's `autogen`; last real work 2025-05. Neither project chose to die *because* of the
  framework, but both froze at the framework's version boundary.
- **The 2026-vintage projects are the most framework-averse.** microsoft/Webwright (created 2026-04,
  5.9k ★) ships **no LLM SDK at all** — nine runtime deps, raw `httpx` against `/v1/responses` and
  `/v1/messages`. omxyz/lumen (created 2026-03) uses three native SDKs behind a 60-line
  `ModelAdapter` interface and doesn't even take a zod dependency. Both are newer than the LangChain
  era and simply never opted in.

### 3.6 Corrections to the prior batch docs

- [`browser-agents-batch-4.md:61`](browser-agents-batch-4.md) says nanobrowser's LLM access is via
  LangChain.js with `@langchain/{openai,anthropic,…}` — **correct and still true** at 2025-11-24
  (9 packages).
- [`browser-agents-batch-1.md:337`](browser-agents-batch-1.md) lists Stagehand's
  `packages/integrations/` adapters — **correct**, but the doc implies these are Stagehand's own LLM
  layer. They are not: they are examples of embedding Stagehand *into* other frameworks. As of v4 the
  Stagehand client has **no LLM dependency at all**.
- [`browser-agents-batch-4.md:595`](browser-agents-batch-4.md) reads DeepResearch as a
  `qwen-agent`-based stack. Half-true: `qwen-agent==0.0.26` is a pinned dep and the older paper
  subprojects use it, but the flagship `inference/react_agent.py` overrides `FnCallAgent`'s loop
  completely and the three newest subprojects (`NestBrowse`, `ParallelMuse`, `AgentFold`) import only
  `openai` + `mcp`.

---

## 4. Migration history and documented reasons

### 4.1 browser-use: LangChain → native (June 2025) — the clearest case in the ecosystem

**Verified timeline.**

| Date | Evidence |
|---|---|
| 2025-01 | `browser-use==0.1.30` core deps: `langchain==0.3.14`, `langchain-openai==0.3.1`, `langchain-anthropic==0.3.3`, `langchain-ollama==0.2.2`, `langchain-fireworks>=0.2.6`, `langchain-aws>=0.2.11`, `langchain-google-genai==2.0.8`, `lmnr[langchain]>=0.4.53` — verified via `gh api .../pyproject.toml?ref=0.1.30` |
| 2025-05-30 | `a11bf24f` "bumped langchain versions and fixed llama 4"; `4048328b` (PR #1863) — maintenance churn |
| 2025-06-05 | `9273d9b1` "Bump langchain" (PR #1868); `c505d3f2` "bump pydantic, langchain, faiss-cpu, mem0ai, …" |
| **2025-06-24** | **`7a10ae0c` "Squashed commit langchain to native"**, branch `feature/squashed-langchain-to-native`, merged as **PR [#2081](https://github.com/browser-use/browser-use/pull/2081) "Switch from Langchain to native model implementations"** — 151 files, +4,097/−3,101 |
| 2025-06-27 | `0.4.1` release notes: *"**BETA** release while we continue **migrating off langchain** and implementing more models + features, wait for 0.4.5 ish for next stable release."* Same release: PR #2150 "**Remove mem0**" |
| 2025-07-08 | `0.5.0` — migration complete |
| today | `browser_use/llm/base.py:1-4`: *"We have switched all of our code from langchain to `openai.types.chat.chat_completion_message_param`. For easier transition we have …"* |

**Documented reasons.** browser-use never published a blog post, so the reasons must be assembled
from primary artefacts. Four are attributable:

1. **Model-swapping friction.** Issue [#546](https://github.com/browser-use/browser-use/issues/546)
   ("LiteLLM-like Facade", the precursor proposal): *"Before you always had to adjust the langchain
   imports. Now you just have to adjust the model string. I find this a big quality of life change."*
2. **Token/cost accounting.** PR #2081's own summary lists as a *new feature*: "Added token usage and
   cost tracking with a new token cost service." Per-provider usage fields are exactly what a
   normalising abstraction flattens away; browser-use's `ChatInvokeCompletion` (`llm/views.py`) carries
   usage as a first-class field.
3. **Dependency-pin blast radius.** Because 0.1.x pinned `langchain==0.3.14` *exactly*, every
   downstream consumer inherited the whole tree — visible in this very survey: steel-dev/surf.new's
   `requirements.txt` pins `langchain-aws==0.2.11` and `langchain-fireworks==0.2.7`, providers its own
   `api/providers.py` never constructs. Issue #3731 ("This project is not compatible with
   langchain-openai") and PR #3736 ("pin `langchain-openai <1.0.0` to resolve dependency conflict")
   show the conflicts persisting *after* the migration, purely from the example extra.
4. **Message-format control.** The replacement is not another abstraction: it is
   `openai.types.chat.chat_completion_message_param` (`llm/base.py:2`) — an on-the-wire type — plus a
   per-provider serialiser. The provider dirs now each own their own quirks (Mistral strips
   `minLength`/`maxLength`/`pattern`/`format`; Google has its own schema fixer).

**Notably, they kept escape hatches rather than purity:** `browser_use/llm/litellm/` exists, and
`ChatLangchain` is documented as an unsupported adapter in `browser_use/llm/README.md` ("Because of
how we implemented the LLMs, we can technically support anything"). PR #4069 ("feat: auto-wrap
LangChain models for seamless compatibility") shows the community pushing back the other way.

### 4.2 Stagehand: own client → Vercel AI SDK → nothing (client-side)

Trajectory verified from `CHANGELOG.md` + tagged manifests:

| Stage | Evidence |
|---|---|
| v1 (late 2024) | Own `LLMClient` interface: PR #367 "Logger in `LLMClient` is inherited by default"; PR #388 "Export `LLMClient` type"; PR #620 "You can now pass in an OpenAI instance as an `llmClient`". Vercel AI SDK arrives as an *example*: PR #382 "**Added example implementation of the Vercel AI SDK as an LLMClient**" |
| v2 (2025) | `lib/llm/` = `OpenAIClient.ts`, `AnthropicClient.ts`, `GoogleClient.ts`, `GroqClient.ts`, `CerebrasClient.ts`, `LLMProvider.ts`, **`aisdk.ts`** (verified at tag `v2.2.0`). Deps: `@anthropic-ai/sdk@0.39.0`, `@google/genai@^0.8`, `openai@^4.87`, **`ai@^4.3.9`**. `@langchain/core` + `@langchain/openai` are **devDependencies only** (evals/examples). Agent side: `lib/agent/` = `AgentClient.ts`, `AnthropicCUAClient.ts`, `OpenAICUAClient.ts`, `StagehandAgent.ts`. PR #698 "Fixing LLM client support to **natively integrate with AI SDK**" |
| v3 (2026) | `packages/core` deps (tag `stagehand-server-v3/v3.7.4`): `ai@^5.0.185`, `@ai-sdk/provider@^2`, plus native `openai`/`@anthropic-ai/sdk`/`@google/genai` and `@modelcontextprotocol/sdk`. AI SDK is now the primary path (changelog #2231, #2068, #1455 all reference AI SDK behaviour) |
| **v4 (2026)** | `packages/sdk-ts/package.json` deps = `@browserbasehq/sdk`, `@opentelemetry/*`, `chrome-launcher`, `zod`. **Zero LLM deps.** Changelog 4.0.0: *"Rebuilt Stagehand around its v4 browser protocol and TypeScript SDK. Stagehand is now a **protocol-first monorepo** with TypeScript, Python, and Go SDKs over a shared core."* The loop lives behind JSON-RPC (`packages/protocol/stagehand.v4.json`) |

**Reason (documented):** the v4.0.0 changeset states the driver plainly — three SDKs (TS, Python, Go)
over one protocol. You cannot ship a Go SDK that reimplements a TypeScript LLM stack; so the LLM
stack stops being the SDK's problem. Note the residual `ClientLLMSchema` /
`removeClientLLMHandler` (`src/clientSchemas.ts:134`, `src/stagehand.ts:178`): the server can call
*back* to a client-supplied model, preserving BYO-LLM without a client-side client.

### 4.3 nanobrowser: Validator agent deleted (August 2025)

PR [#204](https://github.com/nanobrowser/nanobrowser/pull/204), merged 2025-08-22, commit `19d7a823`
"Remove validator agent and transfer responsibilities to planner". Body:

> - Delete validator agent, prompts, and templates
> - Update planner to handle final result formatting and task completion validation
> - **Simplify executor logic with clean periodic planner runs**
> - Remove validator references from UI, storage, and configuration

The current executor comment records the resulting design (`executor.ts:169-171`): *"If navigator
indicates completion, the next periodic planner run will validate it."* One fewer agent, one fewer
prompt surface, same guarantee.

### 4.4 Alibaba DeepResearch: qwen-agent → raw client

Not announced, but visible in the file layout. The older paper subprojects import qwen-agent heavily
(`WebWatcher` 39 files, `WebDancer` 7, `WebWeaver` 7, `WebSailor` 3). The three newest —
`NestBrowse`, `ParallelMuse`, `AgentFold` — import **zero** qwen-agent and go straight to
`AsyncOpenAI`/`OpenAI` plus `mcp.ClientSession`. Even the flagship `inference/react_agent.py` keeps
`FnCallAgent` only as a base class for message plumbing while overriding `_run` with its own
`while num_llm_calls_available > 0` loop against a vLLM port. When you serve your own weights,
a provider abstraction buys nothing and a framework's loop actively gets in the way of custom
context management (see the token-budget compaction at `react_agent.py:186-198`).

### 4.5 UI-TARS: forked its LLM client rather than adopt or write one

`multimodal/tarko/llm-client/README.md:7`: *"This package is forked from
[token.js](https://github.com/token-js/token.js), **For multimodal and Azure OpenAI support, we had
to fork**, thanks to [RPate97](https://github.com/RPate97) for his work."* The third path: take a
small, single-purpose client library and vendor it, because the two things you need (multimodal
content parts, Azure) are exactly the things a normalising layer gets wrong.

### 4.6 LaVague: never migrated, and that is the finding

Verified from the first commit (`78c1459`, 2024-02-27): `requirements.txt` was already
`llama_index`, `llama-index-embeddings-huggingface`, `llama-index-llms-huggingface`,
`llama-index-retrievers-bm25`. `gh api search/commits q=repo:lavague-ai/LaVague+langchain` returns
nothing but the single `RecursiveCharacterTextSplitter` import. LaVague was llama-index-native from
day one, pinned `llama-index = "0.10.56"` and provider packages at `0.1.x`, and stopped receiving
commits 2025-01-21 with those pins intact. 6.4k stars, no migration, no successor.

### 4.7 No project migrated *toward* a general-purpose agent framework

Searched: commit messages, PR titles, changelogs, and release notes across all 15. Every recorded
orchestration migration runs framework → less framework, or client-library → own client:

| Direction | Instances |
|---|---|
| framework/library → own | browser-use (LangChain → native, 2025-06); Stagehand (AI SDK → protocol, 2026); DeepResearch (qwen-agent → raw `AsyncOpenAI`); UI-TARS (token.js → fork); browser-use (mem0 → removed, PR #2150); nanobrowser (validator agent → deleted) |
| own → framework | **none found** |

---

## 5. Recommendation for NetGent v2

### 5.1 What makes NetGent's situation different

NetGent v2 uses an LLM **only at compile time** (`netgent generate` / `netgent eval`), in a
Planner → Discovery fleet → Workflow Generator → Validation Agent pipeline; `netgent run` makes zero
LLM calls ([`OVERVIEW.md`](../OVERVIEW.md) §3.1, §"`v2/.env.example` — the config contract"). Three
consequences that no repo in this survey shares fully:

1. **Latency is nearly free, correctness is not.** A compile runs once per workflow. Spending 3× the
   tokens or 10× the wall-clock on the Generator is acceptable; emitting a graph whose guards are
   subtly wrong is not. This inverts the usual browser-agent trade-off and argues for *more*
   schema strictness and *more* validation passes, not less.
2. **The pipeline is a known-shape DAG with one loop, not open-ended agency.** Planner → Discovery →
   Generator → Validator, with two documented back-edges ("Missing gaps?" Generator → Planner;
   "Script failed?" Validator → Generator). Four stages and two back-edges is not a graph that needs
   a graph library.
3. **The output is a typed artefact, not a chat trajectory.** Everything the LLM produces must
   deserialise into the state/transition/guard IR ([`OVERVIEW.md`](../OVERVIEW.md) §3.1). Structured
   output is the whole interface; conversation is incidental.

### 5.2 Recommendation: custom pipeline + litellm-style client + pydantic schemas

**Do not adopt LangGraph, pydantic-ai, or claude-agent-sdk for the synthesis layer. Write the four
stages as plain async functions and put one thin LLM client behind them.**

Concretely:

```
src/netgent/synthesis/
  llm.py          # ONE call site: acomplete(messages, *, schema: type[BaseModel]) -> BaseModel
                  # litellm.acompletion + per-provider response_format + json_repair fallback
  schemas.py      # pydantic models: Plan, DiscoveryTrace, WorkflowDraft, ValidationReport
  planner.py      # async def plan(goal, input_schema) -> Plan
  discovery.py    # async def discover(plan) -> list[DiscoveryTrace]   (asyncio.gather = the "fleet")
  generator.py    # async def generate(traces) -> WorkflowDraft
  validator.py    # async def validate(draft, cases) -> ValidationReport
  pipeline.py     # the DAG + the two back-edges + budget accounting, ~150 lines
```

**Why this and not LangGraph.** LangGraph buys persistence, checkpointing, streaming, human-in-the-loop
interrupts, and conditional-edge routing over a large state graph. NetGent needs none of them at
compile time: there is no user watching a token stream during `netgent generate`, no interrupt to
resume from mid-compile (a failed compile is re-run, and the expensive artefact — the Discovery trace,
with HAR and saved HTML — is already checkpointed to disk by design, [`OVERVIEW.md`](../OVERVIEW.md)
§3.1). What it costs is real and specific: (a) `langgraph` + `langchain-core` pins in a repo whose
current total dependency list is `typer>=0.15` (`v2/pyproject.toml:11-13`); (b) another
message-normalisation layer between your prompt and the wire, which is exactly the thing browser-use
spent 151 files removing; (c) `AIMessage`/`BaseMessage` in your type signatures instead of your own
IR. **NetGent v1 already ran this experiment**: `langgraph.graph.StateGraph` appears in exactly three
files (`v1/src/netgent/agent.py:1,87`, `components/state_synthesis/state_synthesis.py:1`,
`components/web_agent/web_agent.py:2`) — used purely to sequence a handful of methods
(`_program_controller`, `_state_executor`, `_state_synthesis`, `_web_agent`) that a function would
have sequenced. The nodes are already plain methods on `NetGent`; only the wiring is LangGraph, and
the wiring is the cheap part.

**Why not pydantic-ai.** It is the closest fit of the three — its whole premise (typed outputs,
validation, retries) is what the synthesis layer needs — and it appears in **zero** of the 15
projects surveyed. That is not disqualifying on its own, but the value it adds over
`litellm.acompletion(response_format=Model)` is a retry-on-validation-error loop and a tool-calling
runtime you don't need at compile time. If you want its ergonomics, the 40 lines in §5.4 give you the
same thing with no dependency and no `Agent`/`RunContext` types leaking into the IR.

**Why not claude-agent-sdk.** Wrong shape and wrong coupling. It is an agent harness (its own tool
loop, permissions, session management) tied to one provider — and the compile side must run against
at least Gemini (v1's models were `langchain_google_genai` / `langchain_google_vertexai`, and the
Discovery fleet's screenshot-heavy prompts are where Gemini's pricing matters most). The projects
that ship a Claude-agent-SDK integration (Stagehand `packages/integrations/claude-code/`) ship it as
one adapter among eight, never as the engine.

**Why litellm and not your own client.** Six of fifteen projects rolled their own — but read *who*:
browser-use (109k ★, full-time team, 15 adapter dirs), UI-TARS (ByteDance), Stagehand (Browserbase),
browserable (a hand-rolled table that carries `gpt-4o` and `gemini-2.0-flash` — already stale).
Rolling your own is a standing maintenance tax paid in provider-quirk bugs, and it is the one part of
this stack that is genuinely commoditised. The three closest analogues by *situation* — research-lab
or small-team projects that need many providers and don't want to maintain adapters — all chose
litellm: **Skyvern** (`litellm.Router`, 289 model configs), **notte** (litellm + llamux + json_repair
+ per-provider schema surgery), **SeeAct** (an OSU NLP research artifact, `litellm==1.35.32`, three
engines). SeeAct is the closest peer to NetGent institutionally, and it is a one-file
`engine_factory()` over `litellm.completion`. That is the level of machinery this needs.

**On multi-agent structure:** keep the four stages, but make Discovery the only *fleet*
(`asyncio.gather` over N explorers, which is exactly what DeepResearch's `ParallelMuse` and
`AgentFold` do with `ThreadPoolExecutor`), and make Planner and Validator **functions that call a
model**, not agents with their own loops. The survey is unambiguous here: nanobrowser deleted its
validator agent to simplify the executor (§4.3); notte's validator is a `CompletionValidator` class
with one method (`common/validator.py:39`); browser-use's judge is `construct_judge_messages()` +
one call (`agent/judge.py:44`). The design-doc review already flags the Planner as unfalsifiable
("no plan representation, no hypothesis representation, no adjustment rule",
[`OVERVIEW.md`](../OVERVIEW.md) §3.1) — a pydantic `Plan` schema is the fix, and it is a fix a
framework cannot give you.

### 5.3 The closest precedent: microsoft/Webwright's `skill_factory`

Webwright is the only surveyed project with a genuine **compile-time LLM pipeline** that emits
reusable artefacts and validates them — structurally the same problem as `netgent generate`. What it
does (`src/webwright/skill_factory/`, ~18 modules):

- **Plain functions, no framework.** `build.py` fans out with `ThreadPoolExecutor` +
  `as_completed` (`:35,142`); `learn.py` groups traces into parameterised templates
  (`group_chunk()` `:208`) and calls `evolve()` (`:287`).
- **One indirected LLM call site.** `skill_factory/llm.py` — `configure_llm(model)` sets a
  process-wide default, `llm()` is the only entry point, and its docstring states the design goal:
  *"backend-agnostic, via webwright's own model abstraction. No hardcoded gateway/endpoint/key."*
- **JSON-schema forcing, hand-rolled.** `models/base.py:307` `_response_schema()`;
  `openai_model.py:133-138` sends `{"type":"json_schema","strict":True}`; `base.py:107`
  `parse_json_output()` validates.
- **Validation is a tiered flag, not an agent.** `--verify {off,shape,strict}` and `--verify-rounds`
  (default 2) with `--on-fail {reference,…}` and `--draws` (`learn.py:223,318-331`); the gate
  (`gate.py`) can be `task_id`, gold-answer, or `self_verify` — and `learn.py:248` prints an explicit
  warning when the weak self-verify gate is in use.
- **Nine runtime dependencies, none of them an LLM SDK.**

Two things to lift directly: **tiered verification with an explicitly-labelled weak mode** (NetGent's
Validation Agent has a documented circularity problem — "generate tests that pass to prove dynamism"
with no stated oracle, [`OVERVIEW.md`](../OVERVIEW.md) §3.1; Webwright's answer is to name the gate
in the output and warn when it's the weak one), and **`configure_llm()`** — one process-wide model
handle so Planner/Discovery/Generator/Validator provably share a backend and a budget.

### 5.4 The one abstraction worth writing

Everything the survey converges on fits in one function. This is the whole LLM layer:

```python
# src/netgent/synthesis/llm.py
import litellm
from json_repair import repair_json
from pydantic import BaseModel

async def acomplete[T: BaseModel](
    messages: list[dict], schema: type[T], *, model: str, **kw
) -> T:
    """One LLM call site for the whole compile side. Ladder: json_schema → json_object → repair."""
    for response_format in _ladder(schema, model):        # per-provider schema surgery
        try:
            r = await litellm.acompletion(
                model=model, messages=messages, response_format=response_format, **kw
            )
            content = r.choices[0].message.content
            try:
                return schema.model_validate_json(content)
            except ValueError:
                return schema.model_validate_json(repair_json(content))  # notte/Skyvern pattern
        except litellm.exceptions.BadRequestError:
            continue                                       # model rejected the schema; degrade
    raise SynthesisError(f"{model} produced no parseable {schema.__name__}")
```

Every element is copied from a verified production implementation: litellm from Skyvern
(`api_handler_factory.py:1852`) / notte (`engine.py:8`) / SeeAct
(`demo_utils/inference_engine.py:208`); the per-provider `response_format` ladder from notte
(`engine.py:369-408`); `json_repair` from Skyvern (`llm/utils.py:292`) and notte (`engine.py:9`);
pydantic-schema forcing from browser-use (`service.py:1946` → `llm/openai/chat.py:256,301`);
capability degradation from nanobrowser (`agents/base.ts:107`) and browserable
(`services/llm.js:184+`). Add `litellm.completion_cost(response)` (Skyvern
`api_handler_factory.py:1128`) for the per-run token accounting that [`OVERVIEW.md`](../OVERVIEW.md)
§2 principle 10 requires — and that was reason #2 for browser-use leaving LangChain.

### 5.5 Migration note on v1's LangChain surface

Dropping LangChain from the v2 synthesis layer is small, because v1's usage is already thin —
7 imports across 6 core files, all of them shims:

| v1 site | Import | v2 replacement |
|---|---|---|
| `src/netgent/cli.py:21-22` | `ChatVertexAI`, `ChatGoogleGenerativeAI` | `model="vertex_ai/gemini-…"` / `"gemini/gemini-…"` litellm strings |
| `src/netgent/agent.py:9`, `components/web_agent/web_agent.py:5` | `BaseChatModel` type hint | `str` model id (litellm) or a `Protocol` (browser-use `llm/base.py:18` pattern) |
| `components/web_agent/web_agent.py:3-4`, `components/state_synthesis/state_synthesis.py:4-6` | `SystemMessage`, `HumanMessage`, `ChatPromptTemplate` | `list[dict]` + f-strings or Jinja (Skyvern's `forge/prompts/skyvern/*.j2`) |
| `components/web_agent/web_agent.py:6` | `JsonOutputParser` | `schema.model_validate_json` + `repair_json` (§5.4) |
| `browser/utils/mark_dom.py:7` | `langchain_core.runnables.chain` decorator | plain async function |
| `agent.py:1,87`, `state_synthesis.py:1`, `web_agent.py:2` | `langgraph.graph.StateGraph` | `pipeline.py` — explicit `await` sequence + the two back-edges |

Net effect: `langgraph`, `langchain`, `langchain-core`, `langchain-community`,
`langchain-google-genai`, `langchain-google-vertexai` (six pinned deps in `v1/requirements.txt`)
collapse to `litellm`, `json-repair`, `pydantic`. That is the same trade browser-use made in PR #2081
— and NetGent gets to make it before writing the code rather than after.

### 5.6 Summary of the recommendation

| Layer | Choice | Grounded in |
|---|---|---|
| Orchestration | **Custom** — 4 async functions + `pipeline.py`; no LangGraph | 12/15 surveyed projects; 5/5 above 20k ★; v1's own LangGraph usage was 3 files of pure wiring |
| LLM client | **litellm**, one `acomplete()` call site | Skyvern, notte, SeeAct — the three closest peers by situation; SeeAct is the closest institutionally |
| Structured output | **pydantic + `response_format` ladder + `json_repair`** | browser-use, notte, Webwright, browserable; 6/15 ship a JSON repairer |
| Multi-agent | **Discovery is the only fleet** (`asyncio.gather`); Planner/Generator/Validator are functions | nanobrowser PR #204; notte `CompletionValidator`; DeepResearch ParallelMuse/AgentFold |
| Validation | **Tiered `--verify {off,shape,strict}` + `--verify-rounds`, with the weak gate named in output** | Webwright `skill_factory/learn.py:223,248,318-331` |
| Cost accounting | **`litellm.completion_cost()` per stage, in the artefact** | Skyvern `api_handler_factory.py:1128`; browser-use PR #2081 |
| Escape hatch | Keep one — accept any OpenAI-compatible `base_url` | browser-use kept `llm/litellm/` + `ChatLangchain`; UI-TARS's `openai-compatible` provider |

---

## Appendix A — Reproducing this survey

```bash
mkdir -p /tmp/agent-framework-research && cd /tmp/agent-framework-research
for r in browser-use/browser-use Skyvern-AI/skyvern browserbase/stagehand lavague-ai/LaVague \
         OSU-NLP-Group/SeeAct MinorJerry/WebVoyager EmergenceAI/Agent-E nanobrowser/nanobrowser \
         nottelabs/notte bytedance/UI-TARS-desktop Alibaba-NLP/DeepResearch steel-dev/surf.new \
         microsoft/Webwright omxyz/lumen browserable/browserable; do
  git clone --depth 1 -q "https://github.com/$r.git" "$(echo "$r" | tr '/' '__')" &
done; wait

# historical manifests (shallow clones have no history)
gh api "repos/browser-use/browser-use/contents/pyproject.toml?ref=0.1.30" -H "Accept: application/vnd.github.raw"
gh api "repos/browserbase/stagehand/contents/lib/llm?ref=v2.2.0" --jq '.[].name'
gh api "repos/browserbase/stagehand/contents/packages/core/package.json?ref=stagehand-server-v3/v3.7.4" -H "Accept: application/vnd.github.raw"
gh api "repos/lavague-ai/LaVague/contents/requirements.txt?ref=78c1459215e7ada48a5adbd2992fc6b5c6b01915" -H "Accept: application/vnd.github.raw"

# migration evidence
gh api "search/commits?q=repo:browser-use/browser-use+langchain&per_page=20" \
  --jq '.items[] | "\(.commit.author.date[0:10]) \(.sha[0:8]) \(.commit.message|split("\n")[0])"'
gh api repos/browser-use/browser-use/pulls/2081 --jq .body
gh api repos/browser-use/browser-use/releases/tags/0.4.1 --jq .body
gh api repos/nanobrowser/nanobrowser/pulls/204 --jq .body
gh api repos/browser-use/browser-use/issues/546 --jq .body
```

## Appendix B — Framework-mention audit (what is *absent*)

Greps run across all 15 clones' manifests and `.py`/`.ts` sources:

| Framework | Appears as an orchestration dependency in |
|---|---|
| **LangGraph** | **none of the 15** |
| **CrewAI** | none (only as a Stagehand *integration example*, `packages/integrations/crewai/`) |
| **pydantic-ai** | **none of the 15** |
| **AutoGen / AG2** | Agent-E only |
| **llama-index** | LaVague only (dead) |
| **qwen-agent** | DeepResearch only (and bypassed in its newest code) |
| **OpenAI Agents SDK** | Skyvern, Copilot subsystem only |
| **Vercel AI SDK (`ai`)** | Stagehand v2/v3 (removed in v4); surf.new frontend wire format only |
| **Mastra / deepagents / eve / pi / codex-sdk / claude-agent-sdk** | Stagehand integration examples only |
| **LangChain (as chat-model shim)** | nanobrowser, surf.new. Dev/optional-only: browser-use (`examples` extra), Stagehand v2 (devDeps), notte (`notte-integrations`), LaVague (one text-splitter import), DeepResearch (one evaluator import) |
| **litellm** | Skyvern, notte, SeeAct core; browser-use as an optional adapter (`browser_use/llm/litellm/`); Agent-E documents it as an OpenAI-compatible `base_url` for Ollama |
