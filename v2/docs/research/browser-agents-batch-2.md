# Browser Agents — Batch 2: Academic / Research Agents

Deep dive into four research-oriented open-source browser agents, for the browser-agent survey.

**Method:** each repo was shallow-cloned (`git clone --depth 1`) into `/tmp/browser-agent-research/` and read directly; metadata came from `gh repo view` / `gh api`; benchmark numbers that are *not* in the repos were taken from the corresponding papers (arXiv / ar5iv) and are labeled as such.

**Snapshot date:** 2026-08-16. Star counts and HEAD commits are as of that date.

| Repo | Stars | Language | License | HEAD commit at time of review |
|---|---|---|---|---|
| [OSU-NLP-Group/SeeAct](https://github.com/OSU-NLP-Group/SeeAct) | 850 | Python | OPEN RAIL-S | `2434627` (2025-02-02) |
| [MinorJerry/WebVoyager](https://github.com/MinorJerry/WebVoyager) | 1,119 | Python | Apache-2.0 | `5a78967` (2024-03-04) |
| [THUDM/AutoWebGLM](https://github.com/THUDM/AutoWebGLM) | 929 | Python | Apache-2.0 | `eb8524e` (2024-09-27) |
| [EmergenceAI/Agent-E](https://github.com/EmergenceAI/Agent-E) | 1,249 | Python | MIT | `f218c3c` (2025-05-12) |

**Headline for the survey:** all four are *research artifacts*, not maintained products. Three of the four (SeeAct, WebVoyager, AutoWebGLM's own code) have **zero programmatic tests and zero CI**; Agent-E has a benchmark runner but no unit tests and no CI on `main`. The only pytest suite in this batch is vendored third-party code (WebArena) inside AutoWebGLM, and it is wired to CI infrastructure that does not run in that repo.

---

## SeeAct

LMM-based generalist web agent (GPT-4V + Playwright) from OSU NLP; ICML'24 paper *"GPT-4V(ision) is a Generalist Web Agent, if Grounded"*. **850 stars · Python · OPEN RAIL-S license.**

### Repo/Folder Setup

Two parallel implementations live in the repo: a research codebase (`src/`) and a published PyPI package (`seeact_package/`). They share ~80% of their code by copy, not by import.

```
SeeAct/
├── src/                                # research codebase — run from source
│   ├── seeact.py                       # 887-line main script: demo mode + auto (batch) mode
│   ├── config/                         # TOML configs: demo_mode / auto_mode / online_exp
│   ├── data_utils/                     # dom_utils, image_utils, prompts, format_prompt_utils,
│   │                                   #   evaluation_utils (offline Mind2Web scoring)
│   ├── demo_utils/                     # browser_helper (Playwright), inference_engine (OpenAI/Gemini/
│   │                                   #   Ollama), ranking_model (DeBERTa cross-encoder), website_dict
│   └── offline_experiments/            # Mind2Web offline experiments
│       ├── offline_experiment.py       #   runs GPT-4V over cached queries → prediction-*.jsonl
│       └── screenshot_generation/      #   textual_choices.py / element_attributes.py / image_annotation.py
│                                       #   (build the 3 grounding input formats from the Mind2Web raw dump)
├── seeact_package/                     # pip-installable `seeact` package (v0.2.9.0)
│   ├── seeact/agent.py                 # 932-line SeeActAgent class (public API)
│   ├── seeact/{data_utils,demo_utils}/ # incl. crawler_helper.py (crawler mode)
│   ├── seeact/mark_page.js             # Set-of-Mark (SoM) overlay injection
│   ├── pyproject.toml, requirements.txt, example.py
├── data/
│   ├── online_tasks/                   # merged_online_90_tasks.json (90 live tasks), sample_tasks.json (18)
│   └── examples/                       # 1 bundled Mind2Web action per grounding format (queries.jsonl + images)
└── README.md, LICENSE, CODE_OF_CONDUCT.md
```

**Language / packaging:** Python, setuptools via [`seeact_package/pyproject.toml`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/seeact_package/pyproject.toml) (`requires-python = ">=3.9"`; README recommends conda + Python 3.11). Package deps: `playwright`, `openai==1.24.0`, `litellm==1.35.32`, `google-generativeai==0.5.2`, `backoff`, `toml`, `python-dotenv`. Running from source additionally needs [`seeact_package/requirements.txt`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/seeact_package/requirements.txt): `playwright==1.40.0`, `sentence_transformers` + `torch` (for the candidate ranker), `InquirerPy`, `aioconsole`, `lxml`, `BeautifulSoup4`, `jsonlines`.

**Install & configure:**
```bash
conda create -n seeact python=3.11 && conda activate seeact
pip install seeact
playwright install          # browser kernels
export OPENAI_API_KEY=...   # or GEMINI_API_KEY; Ollama+llava needs no key
```

**Entry points:**
1. **Package API** — [`seeact_package/example.py`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/seeact_package/example.py): `SeeActAgent(model="gpt-4o")` then the async `start() → predict() → execute() → stop()` loop. `SeeActAgent.__init__` takes `model`, `default_task`, `default_website`, `grounding_strategy` (`text_choice` | `text_choice_som`), `config_path`, `save_file_dir`, `temperature`, `crawler_mode`, `crawler_max_steps`.
2. **Demo mode** — `cd src && python seeact.py` (reads `src/config/demo_mode.toml`, prompts for task + URL at the terminal).
3. **Auto/batch mode** — `cd src && python seeact.py -c config/auto_mode.toml` (reads a task JSON from `task_file_path`).

**Notable config knobs** ([`src/config/auto_mode.toml`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/src/config/auto_mode.toml)): `monitor = true` — the agent pauses before *every* action for a terminal `Y/n/i/e` confirmation (accept / reject / human-intervene / end); `max_op`, `max_continuous_no_op`, `dynamic_choice_batch_size`, optional `ranker_path` for the MindAct two-stage candidate ranker ([DeBERTa-v3-base](https://huggingface.co/osunlp/MindAct_CandidateGeneration_deberta-v3-base)), plus Playwright video/tracing and a hardcoded Columbus-OH geolocation. Logins are deliberately unsupported.

### Evals

**Benchmarks:** Mind2Web / [Multimodal-Mind2Web](https://huggingface.co/datasets/osunlp/Multimodal-Mind2Web) offline, plus a *new* online live-website setting the paper introduced (90 Mind2Web-derived tasks on real sites).

**Reported scores** (from the paper, via ar5iv; whole-task success rate %, "Offline₀/₁" = no error tolerance / one-step tolerance):

| System | Offline₀ | Offline₁ | **Online** |
|---|---|---|---|
| FLAN-T5-XL (fine-tuned) | 4.4 | 24.4 | 8.9 |
| GPT-4 (text-only) | 1.1 | 12.2 | 13.3 |
| SeeAct<sub>Choice</sub> (best real grounding) | 3.3 | 12.2 | **37.8** |
| SeeAct<sub>Oracle</sub> (manual/oracle grounding) | 13.3 | 27.8 | **51.1** |

Offline Mind2Web **step success rate** (GPT-4V, 30-task subset per split — cross-task / cross-website / cross-domain):

| Grounding | Cross-Task | Cross-Website | Cross-Domain |
|---|---|---|---|
| Element attributes | 16.1 | 12.1 | 19.0 |
| Image annotation (SoM) | 20.3 | 13.9 | 23.7 |
| Textual choices | 39.1 | 32.7 | 42.0 |
| Oracle | 61.9 | 65.0 | 62.1 |

The paper's central claim rests on this gap: grounding, not planning, is the bottleneck, and SoM-style image annotation *underperforms* textual choices for web agents.

**Where the eval code lives:**
- Offline generation: [`src/offline_experiments/offline_experiment.py`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/src/offline_experiments/offline_experiment.py) — iterates `data/examples/<grounding>/<action_id>/queries.jsonl`, makes the two-stage GPT-4V calls, writes `prediction-<split>.jsonl`.
- Offline input construction: [`src/offline_experiments/screenshot_generation/`](https://github.com/OSU-NLP-Group/SeeAct/tree/main/src/offline_experiments/screenshot_generation) — `textual_choices.py`, `element_attributes.py`, `image_annotation.py`.
- Offline scoring: [`src/data_utils/evaluation_utils.py`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/src/data_utils/evaluation_utils.py) — `format_input_multichoice()`, `posthoc_evaluate_dataset()`, `evaluate_dataset_llm()`.
- Online: `python src/seeact.py -c config/online_exp.toml` with the task list in [`data/online_tasks/merged_online_90_tasks.json`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/data/online_tasks/merged_online_90_tasks.json).

**Reproducibility caveats (concrete):**
- [`src/config/online_exp.toml`](https://github.com/OSU-NLP-Group/SeeAct/blob/main/src/config/online_exp.toml) points `task_file_path` at `../data/online_tasks/task_50_merged.json`, **which is not in the repo** (only `merged_online_90_tasks.json` and the 18-task `sample_tasks.json` ship). It also sets `ranker_path = "../model/deberta-v3-base"`, a model you must download separately.
- `offline_experiment.py` has a literal `api_key="Your API Key"` placeholder and only walks the single bundled example directory (3 queries). Reproducing the paper's offline table requires the ~300 GB Mind2Web raw dump plus a query-source archive hosted on OSU SharePoint.
- **Online success is scored by humans.** There is no automated success checker for live-site runs in the repo; the harness saves screenshots, traces, and a terminal log, and a person judges the trajectory.

### Test Cases

**None.** There is no test framework, no `tests/` directory, and no test file anywhere in the repo — a grep for `pytest`, `unittest`, and `def test_` across all `.py`/`.toml`/`.txt`/`.yml` files returns zero hits. There is no `.github/` directory, so **no CI**: the single workflow the GitHub API reports for the repo is the dynamic `copilot-pull-request-reviewer` app, not a repo-defined pipeline.

The de-facto correctness mechanism is the human-in-the-loop `monitor = true` setting (approve/reject every action) plus manual inspection of the saved screenshots and Playwright traces.

---

## WebVoyager

End-to-end multimodal web agent (GPT-4V + Selenium + Set-of-Mark) from Tencent AI Lab / Zhejiang; the repo that defines the widely reused **WebVoyager benchmark**. **1,119 stars · Python · Apache-2.0.**

### Repo/Folder Setup

Flat, single-purpose research repo — no package, no module hierarchy.

```
WebVoyager/
├── run.py                 # 504 lines — the whole agent loop (Selenium driver, SoM screenshots, GPT-4V calls)
├── utils.py               # 405 lines — get_web_element_rect() (JS bounding-box injection), image encode/resize,
│                          #   extract_information() (action parser), context clipping, PDF answer retrieval
├── utils_webarena.py      # 389 lines — accessibility-tree extraction, adapted from WebArena (text-only mode)
├── prompts.py             # SYSTEM_PROMPT (multimodal) and SYSTEM_PROMPT_TEXT_ONLY (a11y tree)
├── run.sh                 # canonical launch script
├── requirements.txt       # openai==1.1.1, selenium==4.15.2, pillow==10.1.0  (that's all)
├── data/
│   ├── WebVoyager_data.jsonl    # 643 tasks over 15 sites (41–46 tasks each)
│   ├── reference_answer.json    # short reference answers per task
│   ├── GAIA_web.jsonl           # 90 web-browsing tasks lifted from GAIA validation (Level 1 & 2)
│   └── tasks_test.jsonl         # the file run.py actually reads — ships with 1 sample task
├── evaluation/
│   ├── auto_eval.py             # GPT-4V-as-judge automatic evaluator
│   └── run_eval.sh              # launcher for it
├── results/examples/            # 15 recorded trajectories (interact_messages.json + screenshots)
├── downloads/                   # agent PDF downloads land here
└── assets/                      # incl. webvoyager_overall_res.png — the paper's results table
```

**Install & configure:** conda + Python 3.10, `pip install -r requirements.txt`, and a local **Chrome** install (Selenium 4.15 auto-manages the driver, so no manual ChromeDriver). On Linux servers the README suggests `chromium-browser`. **The OpenAI key is a CLI flag, not an env var** (`--api_key`), which means it is baked into `run.sh` — worth flagging for anyone adapting this code.

**Entry point:** `bash run.sh`, which is:
```bash
nohup python -u run.py --test_file ./data/tasks_test.jsonl --api_key YOUR_OPENAI_API_KEY \
  --headless --max_iter 15 --max_attached_imgs 3 --temperature 1 --fix_box_color --seed 42 > test_tasks.log &
```
Text-only ablation adds `--text_only --api_model gpt-4-1106-preview --max_attached_imgs 1`. Other flags: `--save_accessibility_tree`, `--force_device_scale`, `--window_width/height` (default 1024×768), `--output_dir`, `--download_dir`.

The workflow is deliberately manual: you copy the tasks you want from `data/WebVoyager_data.jsonl` into `data/tasks_test.jsonl`, hand-update dates on time-sensitive Booking / Google Flights tasks, then run. Set-of-Mark bounding boxes come from `utils.get_web_element_rect()` (a JS injection derived from [GPT-4V-Act](https://github.com/ddupont808/GPT-4V-Act)); `--fix_box_color` pins them black.

### Evals

This repo **is** the benchmark, so "evals" and "the product" are the same thing.

**Benchmarks:** WebVoyager (643 live tasks across Allrecipes, Amazon, Apple, ArXiv, BBC News, Booking, Cambridge Dictionary, Coursera, ESPN, GitHub, Google Flights, Google Map, Google Search, Huggingface, Wolfram Alpha) + a 90-task GAIA web subset (`data/GAIA_web.jsonl`, all starting from Google Search).

**Reported scores** — Task Success Rate, from the paper's Table 1, which ships in the repo as [`assets/webvoyager_overall_res.png`](https://github.com/MinorJerry/WebVoyager/blob/main/assets/webvoyager_overall_res.png):

| System | Overall | Low outlier | High outlier |
|---|---|---|---|
| GPT-4 (All Tools) | 30.8% | Google Flights 2.4% | Google Search 60.5% |
| WebVoyager text-only (a11y tree) | 40.1% | Booking 2.3% | Google Search 67.4% |
| **WebVoyager (multimodal)** | **59.1%** | ESPN 38.6% | Google Search 76.7% |
| WebVoyager* (GPT-4V auto-eval) | 57.1% ±0.2% | Booking 32.6% | Google Search 77.5% |
| WebVoyager text-only* (auto-eval) | 44.3% ±0.6% | Booking 2.3% | Google Search 75.2% |

Human-expert labels for the unstarred rows; starred rows are the GPT-4V automatic evaluator run three times (κ = 0.70 against humans). The paper reports **85.3% agreement** between the automatic metric and human judgment.

**Eval code:** [`evaluation/auto_eval.py`](https://github.com/MinorJerry/WebVoyager/blob/main/evaluation/auto_eval.py) + [`evaluation/run_eval.sh`](https://github.com/MinorJerry/WebVoyager/blob/main/evaluation/run_eval.sh). Launch:
```bash
cd evaluation && bash run_eval.sh     # after editing api_key and process_dir inside the script
# → python -u auto_eval.py --api_key ... --process_dir ../results/examples --max_attached_imgs 15
```
How it works: for each result directory it parses the task text and the final `Action: ANSWER` out of `interact_messages.json`, base64-encodes the last *k* screenshots, sends them to GPT-4V with an evaluator system prompt, and maps the verdict to `1` (SUCCESS) / `0` (NOT SUCCESS) / `None` (unparseable). `main()` loops over a **hardcoded list of the 15 site names** and indices `0..45`, looking for `task<Site>--<idx>` directories, and prints a per-site list of verdicts — it does **not** compute or persist an aggregate success rate; that arithmetic is left to the user.

### Test Cases

**None.** No pytest/unittest, no `tests/` directory, no `def test_` anywhere, and **no CI** (`gh api repos/MinorJerry/WebVoyager/actions/workflows` → `total_count: 0`; there is no `.github/` directory).

The closest thing to regression material is [`results/examples/`](https://github.com/MinorJerry/WebVoyager/tree/main/results/examples): 15 checked-in trajectories (one per site, e.g. `taskBooking--1/` with 9 screenshots, `taskCambridge Dictionary--29/` with 12 screenshots in both boxed and `_no_box` variants) plus their `interact_messages.json`. They exist so `auto_eval.py` has something to run against out of the box, and so readers can eyeball what a good trajectory looks like — not as assertions.

---

## AutoWebGLM

ChatGLM3-6B-based web navigating agent from THUDM (KDD'24), with HTML simplification, curriculum training, and RL/rejection sampling. **929 stars · Python · Apache-2.0.**

### Repo/Folder Setup

This is an **evaluation-and-data release, not a runnable agent release**: the fine-tuned AutoWebGLM model weights are not in (or linked from) the repo, and the README points you to [THUDM/chatglm3-6b](https://huggingface.co/THUDM/chatglm3-6b) for inference code. What ships is the benchmark data plus three modified evaluation environments.

```
AutoWebGLM/
├── eval.py                 # 136 lines — offline scorer for AutoWebBench + Mind2Web predictions
├── autowebbench/           # the paper's new bilingual benchmark, {source, target} pairs
│   ├── en/ind/test.json    # 349 items      en/ood/test.json  # 338
│   └── zh/ind/test.json    # 392 items      zh/ood/test.json  # 372
├── mind2web/               # Mind2Web converted to the same simplified-HTML prompt format
│   ├── task/test.json      # 1,915 steps    website/test.json  # 1,283    domain/test.json  # 5,496
├── miniwob++/              # modified MiniWoB++ harness
│   ├── main.py             # TestMiniwob driver (gymnasium + miniwob 1.0)
│   ├── html_tools/         # the HTML simplification algorithm (html_parser, identifier, prompt, configs)
│   ├── miniwob_tools/      # action parser, testcases list, DOM/pixel helpers
│   ├── llms/               # CallLLM + providers/gpt.py
│   ├── monitor.py          # nvidia-smi GPU scheduler for parallel runs
│   ├── requirements.txt, install_dependency.sh (apt: chromium + libs), setup.sh (EMPTY — 0 bytes)
├── webarena/               # vendored, modified copy of web-arena-x/webarena
│   ├── run.py, parallel_run.sh, prepare.sh, minimal_example.py, setup.py/setup.cfg
│   ├── browser_env/        # + browser_env/html_tools/ (AutoWebGLM's simplification injected here)
│   ├── agent/prompts/raw/  # + new_action_prompt.py (the paper's action space)
│   ├── evaluation_harness/, llms/providers/{openai_utils,hf_utils,ours}.py
│   ├── solver/             # AutoWebGLM addition: hardcoded action sequences for specific task ids
│   ├── config_files/       # test.raw.json → 812 WebArena tasks
│   ├── tests/              # inherited pytest suite (see below)
│   └── .github/workflows/  # inherited CI — INERT in this repo (nested, not at root)
└── assets/framework.png, README.md, LICENSE
```

**Language / packaging:** Python, but **no root `requirements.txt`, `setup.py`, or `pyproject.toml`.** Each sub-environment installs separately:
- `eval.py` needs `rouge_chinese`, `jieba`, `numpy` — none declared anywhere.
- `miniwob++/requirements.txt`: `gymnasium==0.29.0`, `miniwob==1.0`, `openai==1.3.7`, `transformers==4.35.2`, `lxml`, `Pillow` (listed twice, at two versions). `install_dependency.sh` apt-installs chromium and its shared libs for Selenium. `setup.sh` exists but is a **zero-byte file**.
- `webarena/`: conda Python 3.10 → `pip install -r requirements.txt` (`playwright==1.32.1`, `openai==0.27.0`, `transformers==4.33.2`, `beartype`, `gymnasium`) → `playwright install` → `pip install -e .`; dev extras (`pytest==7.1.2`, `mypy==0.991`, `pytest-asyncio`, `pre-commit`) in `webarena/setup.cfg`.

**Configuration:** WebArena needs the standard self-hosted site URLs exported as env vars (`SHOPPING`, `SHOPPING_ADMIN`, `REDDIT`, `GITLAB`, `MAP`, `WIKIPEDIA`, `HOMEPAGE`) plus `OPENAI_API_KEY`, then `python scripts/generate_test_data.py` to expand `config_files/test.raw.json` (812 tasks) into per-task JSON, and `python browser_env/auto_login.py` (via `prepare.sh`) to mint auth cookies into `./.auth`.

**Entry points:**
- Offline scoring: `python eval.py [result_path]`
- MiniWoB++: `python main.py [cudas] [test-amount] [model-path] [result-path]` (e.g. `python main.py 0,1,2 10 model_path/ result/`; `model-path=manual` enables human stepping)
- WebArena, single task: `python run.py --instruction_path agent/prompts/jsons/new_action_prompt.json --model gpt-3.5-turbo --mode completion --observation_type html --action_set_tag id_html_nasc_tree --result_dir <dir> --test_start_idx 0 --test_end_idx 1`
- WebArena, full sweep: `bash parallel_run.sh` (tmux, 4 panes/GPUs, splits at indices 0/203/406/609/812, `--provider ours` to hit a locally served model, auto-retry loop guarded by `scripts/check_error_runs.py`)

### Evals

The repo is essentially all eval. Four benchmarks:

1. **AutoWebBench** (the paper's contribution) — bilingual EN/ZH, in-domain and out-of-domain splits, 1,451 items total, stored as `{source, target}` where `source` is the simplified-HTML prompt and `target` is a function-call action like `click(A)` / `type_string(E, "...")`.
2. **Mind2Web** — same format, 8,694 steps across the three standard splits.
3. **MiniWoB++** — 56 tasks.
4. **WebArena** — 812 tasks.

**Reported scores** (from the paper; the README itself contains **no results tables at all**):

| Benchmark | AutoWebGLM-6B | GPT-4 | GPT-3.5-Turbo | Best other baseline |
|---|---|---|---|---|
| AutoWebBench EN (in-domain / OOD), step SR | **64.8 / 58.6** | 38.6 / 39.7 | 12.1 / 6.4 | Qwen-7B 9.0 / 7.6 |
| AutoWebBench ZH (in-domain / OOD), step SR | **65.4 / 61.8** | 36.7 / 36.3 | 13.5 / 10.8 | Qwen-7B 9.1 / 7.5 |
| Mind2Web step SR (task / website / domain) | **66.4 / 56.4 / 55.8** (avg 59.5) | 36.2 / 30.1 / 26.4 | 17.4 / 16.2 / 18.6 | Html-T5-XL 66.9 avg |
| MiniWoB++ (56 tasks × 100 episodes) | **89.3%** | 32.1% | 13.4% | Html-T5-XL 85.6% |
| WebArena success rate | **18.2%** | 14.4% | 6.2% | Lemur-70B 5.3% |

(Baselines marked in the paper with `*` were fine-tuned on the respective training sets.)

**Where eval code lives and how it's launched:**
- [`eval.py`](https://github.com/THUDM/AutoWebGLM/blob/main/eval.py) — `python eval.py [result_path]` over a JSONL of `{predict, labels}`. It regex-parses the predicted function call, then reports four means: `type` (action-type accuracy), `label` (element-id accuracy), `param` (ROUGE-1 F1 over the argument string, jieba-tokenized for Chinese), and `all` (type **and** label both exact). Note it scores *your* saved model outputs — it does not run a model.
- MiniWoB++: `miniwob++/main.py`; results land in `log_files/*.log` as per-case `{"task": ..., "case_id": ..., "result": 1.0}` lines, then per-task `avg_score`, then an overall `all` line.
- WebArena: `webarena/run.py` / `webarena/parallel_run.sh`, scored by the inherited `webarena/evaluation_harness/evaluators.py`.

**Caveats:** `parallel_run.sh` ends with `python get_result.py ${result_dir}` — **that file does not exist in the repo**. The model weights needed to reproduce any AutoWebGLM row are also absent, so the repo supports *scoring* and *environment setup* but not end-to-end reproduction.

### Test Cases

**AutoWebGLM's own code has no tests and no CI.** `gh api repos/THUDM/AutoWebGLM/actions/workflows` returns `total_count: 0`, and there is no root `.github/`.

The only test suite is **inherited verbatim inside the vendored `webarena/` copy** — ~44 test functions, pytest + `pytest-asyncio`, configured by `[tool.pytest.ini_options] testpaths = ["tests"]` in `webarena/setup.cfg`:

```
webarena/tests/
├── conftest.py                              # fixtures spawning headless ScriptBrowserEnv /
│                                            #   AsyncScriptBrowserEnv, incl. a11y-tree and
│                                            #   current-viewport-only variants
├── test_browser_env/
│   ├── test_actions.py                      # pure unit: test_is_equivalent, test_action2create_function
│   ├── test_action_functionalities.py       # 11 tests: click/hover/type/scroll/key-press by element id,
│   │                                        #   test_inter_page_actions, test_e2e_id_based_actions
│   ├── test_playwright_actions.py           # 5 tests: frame_locator, hover, select_option, xpath
│   ├── test_script_browser_env.py           # 9 tests: test_parallel_script_browser_env,
│   │                                        #   test_accessibility_tree_observation_update,
│   │                                        #   test_multiple_start_url, test_observation_tab_information
│   └── test_auth_cookie.py                  # sync + async cookie auth against the self-hosted sites
└── test_evaluation_harness/
    ├── test_evaluators.py                   # 12 success/fail pairs over string_match, url_exact_match,
    │                                        #   html_content(_element)_match, func eval, url+func combos
    ├── test_helper_functions.py             # test_gitlab_get_project_memeber_role
    └── configs/*.json                       # 9 task-config fixtures driving the evaluator tests
```

The most interesting pattern for a survey: the evaluator tests use a `TeacherForcingAgent` that replays a scripted action string (e.g. `page.stop("The date is 1985/04/18")`) through the real browser env, then asserts the evaluator returns 1.0 or 0.0 — testing the *grader*, not the agent. `test_parallel_script_browser_env` checks that multiple browser envs can run concurrently.

**CI status:** `webarena/.github/workflows/tests.yml` (mypy `--strict` + `pytest` on every push, after `prepare.sh` re-mints login cookies) and `webarena/.github/workflows/pre-commit.yml` (black line-length 79, isort, nbstripout, trailing-whitespace) are present as files but **never execute** — GitHub only reads workflows from the repository-root `.github/workflows/`, and this copy is nested one level down. Even if hoisted, `tests.yml` hardcodes `ec2-3-131-244-37.us-east-2.compute.amazonaws.com` WebArena instances that no longer exist.

---

## Agent-E

Hierarchical AG2/AutoGen-based web automation agent from Emergence AI (planner + browser-nav agent, DOM distillation); the commercial-adjacent research repo behind the Emergence web-automation API. **1,249 stars · Python · MIT.**

### Repo/Folder Setup

```
Agent-E/
├── ae/                              # the package
│   ├── main.py                      # CLI entry (python -m ae.main)
│   ├── main_no_skills_nav.py        # ablation entry: no skills-based navigation
│   ├── config.py                    # PROJECT_ROOT / PROJECT_TEST_ROOT / log + temp folder bootstrapping
│   ├── core/
│   │   ├── agents/                  # high_level_planner_agent.py, browser_nav_agent.py
│   │   ├── skills/                  # 10 atomic skills: click_using_selector, enter_text_and_click,
│   │   │                            #   enter_text_using_selector, get_dom_with_content_type, get_url,
│   │   │                            #   get_user_input, open_url, pause_flow, press_key_combination,
│   │   │                            #   pdf_text_extractor + skill_registry.py (dynamic registration)
│   │   ├── autogen_wrapper.py       # AG2 wiring; playwright_manager.py; system_orchestrator.py
│   │   ├── prompts.py, ui_manager.py, notification_manager.py, post_process_responses.py
│   │   └── memory/static_ltm.py     # long-term memory from user_preferences/user_preferences.txt
│   ├── server/api_routes.py         # FastAPI wrapper (POST /execute_task)
│   ├── ui/injectOverlay.js          # in-browser chat overlay
│   └── utils/                       # get_detailed_accessibility_tree.py, dom_mutation_observer.py,
│                                    #   detect_llm_loops.py, response_parser.py, per-provider LLM helpers
├── test/                            # BENCHMARK harness (not a unit-test suite — see Test Cases)
│   ├── run_tests.py, tests_processor.py, evaluators.py, test_utils.py
│   ├── test_config_auditor.py, test_tasks_formatter.py   # maintenance scripts despite the names
│   └── tasks/                       # test.json (32), webvoyager_test.json (643),
│                                    #   webvoyager_sampled_data.json (65), annotator_dry_run_...30.json (30)
├── scripts/
│   ├── aggregate_test_results.py    # pandas roll-up into per-site tables
│   └── webvoyager_to_agente_test_converter.py
├── docs/                            # Sphinx sources + prebuilt _build
├── install.sh / win_install.ps1 / run.sh
├── pyproject.toml, requirements.txt, agents_llm_config-example.json, .check-env-example
└── .github/ISSUE_TEMPLATE/          # ← the entire .github directory. No workflows.
```

**Language / packaging:** Python ≥3.10 (installer creates 3.11), **`uv`** for env + deps, [`pyproject.toml`](https://github.com/EmergenceAI/Agent-E/blob/main/pyproject.toml) declaring `autogen~=0.7` (AG2) with `[anthropic]`/`[groq]` extras, `playwright==1.44.0`, `fastapi==0.111.1` + `uvicorn`, `anthropic`, `google-generativeai`, `nltk`, `pdfplumber`, `pydantic`, `tabulate`. Dev extra: `ruff`, `sphinx`. Ruff is configured (bugbear/pycodestyle/pyflakes/isort/pyupgrade, `line-length = 250`) but only runs if you invoke it.

**Install & configure:**
```bash
./install.sh -p            # or .\win_install.ps1 -p  — installs uv, makes .venv, installs deps + Playwright
cp .env-example .env       # then edit
python -m ae.main          # macOS: python -u -m ae.main
```
Env vars ([`.check-env-example`](https://github.com/EmergenceAI/Agent-E/blob/main/.check-env-example) + README): `AUTOGEN_MODEL_NAME`, `AUTOGEN_MODEL_API_KEY`, optional `AUTOGEN_MODEL_BASE_URL` / `_API_TYPE` / `_API_VERSION` (Azure, Groq, LiteLLM+Ollama), `AUTOGEN_LLM_TEMPERATURE` / `_TOP_P` (defaults 0.0 / 0.001 / seed 12345 for `gpt-*`), `BROWSER_STORAGE_DIR` (path to a real Chrome profile instead of Playwright's browser), `SAVE_CHAT_LOGS_TO_FILE`, `LOG_MESSAGES_FORMAT`, `ADDITIONAL_SKILL_DIRS` (load extra skills from arbitrary dirs/files), `PLANNER_USER_INPUT_SKILL_ENABLED`, and `AGENTS_LLM_CONFIG_FILE` + `AGENTS_LLM_CONFIG_FILE_REF_KEY` for per-agent JSON model config. `OPENAI_API_KEY` is separately required by the benchmark harness's LLM-based evaluators.

**Entry points:** (1) `python -m ae.main` / `./run.sh` — launches Chrome with an injected chat overlay; (2) `uvicorn ae.server.api_routes:app --reload --loop asyncio` then `POST /execute_task` with `{"command": "...", "llm_config": {...}}`; (3) `python -m test.run_tests` for the benchmark harness.

### Evals

**Benchmark:** WebVoyager (all 643 tasks), evaluated on live sites.

**Reported scores** (paper, arXiv:2407.13032): Agent-E **73.2%** overall vs. the WebVoyager multimodal agent **57.1%** and the text-only Wilbur agent **52.6%** — beating both on 11 of 15 sites, with a per-site range of **27.3% (Booking.com) to 95.7% (WolframAlpha)**. The paper also reports efficiency metrics that most agent papers omit: mean task time **150 s** (successful) / **220 s** (failed), **~25 LLM calls per task** (6.4 planner + 18.6 browser-nav), and self-recognized failure in 52% of failed tasks. Scoring was done by **five human evaluators** with written justifications, requiring full task completion to count as a pass.

Important repro caveat stated in the README itself: *"The WebVoyager validation used the [`nested_chat_for_hierarchial_planning`](https://github.com/EmergenceAI/Agent-E/tree/nested_chat_for_hierarchial_planning) branch and GPT4-Turbo"* — not `main`.

**Where the eval code lives:**
- [`test/run_tests.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/run_tests.py) — argparse CLI → `tests_processor.run_tests()`.
- [`test/tests_processor.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/tests_processor.py) (418 lines) — per-task: navigate to `start_url`, hand `intent` to `AutogenWrapper.process_command`, extract the agent's `final_response`, route to an evaluator, and record `score`, `reason`, `tct` (wall-clock), and `compute_cost` (prompt/completion/total tokens + $) into `test/results/`; per-task chat logs into `test/logs/`; prints a tabulated per-task Pass/Fail/Skip line and a progress bar.
- [`test/evaluators.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/evaluators.py) (437 lines) — WebArena-derived `StringEvaluator`, `URLEvaluator`, `HTMLContentEvaluator`, plus Agent-E's own `ManualContentEvaluator`, combined by `EvaluatorComb` and selected by `evaluator_router()`.
- [`test/test_utils.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/test_utils.py) — `llm_fuzzy_match()` and `llm_ua_match()` (GPT-as-judge for fuzzy answers/unachievable tasks), `evaluate_exact_match`, `evaluate_must_include`.
- [`scripts/aggregate_test_results.py`](https://github.com/EmergenceAI/Agent-E/blob/main/scripts/aggregate_test_results.py) — pandas roll-up keyed by a `URL_ALIAS_MAP` of the 15 WebVoyager sites.
- [`scripts/webvoyager_to_agente_test_converter.py`](https://github.com/EmergenceAI/Agent-E/blob/main/scripts/webvoyager_to_agente_test_converter.py) — joins WebVoyager's `WebVoyager_data.jsonl` + `reference_answer.json` into Agent-E's WebArena-style task schema.

**How an eval run is launched:**
```bash
python -m test.run_tests                                   # defaults to test/tasks/test.json
python -m test.run_tests --min_task_index 0 --max_task_index 28 --test_results_id first_28_tests
python -m test.run_tests -config test/tasks/webvoyager_test.json --take_screenshots true
```

**Task files and how they're scored:**

| File | Tasks | eval_types |
|---|---|---|
| `test/tasks/test.json` | 32 | `url_match` 18, `string_match` 12, `program_html` 5 (fully automatic) |
| `test/tasks/webvoyager_test.json` | 643 | `manual` (all) |
| `test/tasks/webvoyager_sampled_data.json` | 65 | `manual` |
| `test/tasks/annotator_dry_run_webvoyager_tasks_30.json` | 30 | `manual` |

`manual` means `ManualContentEvaluator` **pauses the run and prompts the operator at the terminal** — it prints the task, the agent's answer, and the golden/possible reference, then reads `Pass` / `Fail` / `Skip` (scored 1.0 / 0.0 / −0.1) and asks for a free-text reason on anything non-passing. So the headline 73.2% is a human-annotated number produced through this harness, not an automatic one.

### Test Cases

**There is no unit-test suite.** No pytest, no unittest, no test-discovery config anywhere in the repo. `test/` is the benchmark runner described above, and the two files whose names look like tests are actually one-shot maintenance scripts:

- [`test/test_config_auditor.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/test_config_auditor.py) — renumbers `task_id` to match list position and expands `{{placeholder}}` templates from `instantiation_dict` into `intent`, rewriting `test/tasks/test.json` in place.
- [`test/test_tasks_formatter.py`](https://github.com/EmergenceAI/Agent-E/blob/main/test/test_tasks_formatter.py) — copies `task_id` to `task_alias`, renumbers, adds `task_index`. It calls both functions **at module import time** against `test/tasks/webvoyager_test.json`, so any test runner that collected it by name would rewrite a data file as a side effect.

The nearest thing to integration tests is the 32-task automatic set in `test/tasks/test.json`, which does assert concrete outcomes against live websites — e.g. task 3, *"What is the price of Rabbit R1 on https://www.rabbit.tech/?"* → `string_match` with `must_include: ["199"]`; several Amazon sort tasks → `url_match` on the final URL; five tasks → `program_html` DOM assertions. The README is explicit that these are inherently flaky: *"Agent-E operates in a real-world web environment... not all tests may pass consistently due to changes in live websites."*

**CI: none on `main`.** The `.github/` directory contains only `ISSUE_TEMPLATE/` (bug report, feature request, general query). The GitHub API does report one workflow — *Black Duck Security Scan* (`.github/workflows/blackducksca-workflow.yml`) — but it exists only on the side branch `blackduck-security-scan-app-1775749677983` and its runs (most recently May 2026) are all on that branch. No lint, type-check, or test job runs on pull requests; `CONTRIBUTING.md` and the README instead ask contributors to run `python -m test.run_tests` by hand before opening a PR.

---

## Cross-Repo Comparison

| | SeeAct | WebVoyager | AutoWebGLM | Agent-E |
|---|---|---|---|---|
| **Browser driver** | Playwright (async) | Selenium 4.15 + Chrome | Playwright (WebArena), Selenium (MiniWoB++) | Playwright 1.44 (or local Chrome profile) |
| **Observation** | HTML candidates + screenshot; SoM optional | Screenshot + Set-of-Mark; a11y tree in text-only mode | Simplified HTML (custom algorithm) | Distilled DOM / a11y tree (`mmid` injection) |
| **Packaging** | PyPI `seeact` + source tree | none (scripts) | none (three sub-envs) | `uv` + pyproject |
| **Agent architecture** | Single LMM, 2-stage generate→ground | Single LMM loop | Fine-tuned 6B model | AG2 planner + browser-nav agents, skill library |
| **Own benchmark** | Online Mind2Web (90 tasks) | **WebVoyager (643)** + GAIA-web (90) | **AutoWebBench (1,451)** | reuses WebVoyager |
| **Auto-scoring in repo** | offline only (`evaluation_utils.py`) | GPT-4V judge (`auto_eval.py`) | `eval.py` (exact-match + ROUGE) | 3 automatic evaluators + LLM fuzzy match |
| **Human in the loop** | yes (per-action monitor + online scoring) | yes (primary protocol) | no (offline scoring) | yes (`manual` evaluator prompts operator) |
| **Unit tests** | none | none | none of its own (vendored WebArena suite only) | none |
| **CI on default branch** | none | none | none | none |
