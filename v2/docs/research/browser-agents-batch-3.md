# Browser Agent Research — Batch 3: Benchmark/Environment Repos with Agent Baselines

Survey of four open-source benchmark/environment repositories that also ship agent baselines.
Researched 2026-08-16 via shallow clones + docs/paper fetches. Star counts and commit dates as of that date.

**Batch at a glance**

| Repo | Stars | Lang | Env type | Tasks | Primary metric | Tests | CI |
|---|---|---|---|---|---|---|---|
| [web-arena-x/webarena](https://github.com/web-arena-x/webarena) | 1,579 | Python | Live self-hosted websites (Docker/AMI) | 812 | End-to-end task success rate | 31 pytest tests | ✅ pytest + mypy strict + pre-commit |
| [OSU-NLP-Group/Mind2Web](https://github.com/OSU-NLP-Group/Mind2Web) | 1,018 | Jupyter/Python | Static offline HTML traces | 2,350 (1,009 train / 1,341 test) | Element Acc, Op F1, Step SR, SR | **none** | **none** |
| [princeton-nlp/WebShop](https://github.com/princeton-nlp/WebShop) | 583 | Python | Simulated Flask e-commerce site + gym | 12,087 instructions (500 test) | Task Score (100×reward), Success Rate | 17 pytest tests | ✅ pytest |
| [McGill-NLP/weblinx](https://github.com/McGill-NLP/weblinx) | 163 | Python | Offline multi-turn dialogue demonstrations | 2,337 demonstrations | Overall score (IM × IoU/chrF/URLF) | 7 unittest tests | ✅ unittest + PyPI publish + Pages |

---

## WebArena

> Self-hostable web environment of five fully functional websites (shopping, e-commerce CMS, Reddit clone, GitLab, OpenStreetMap) plus 812 human-authored tasks with programmatic evaluators. Canonical implementation of the NeurIPS-era "WebArena: A Realistic Web Environment for Building Autonomous Agents" paper.
> **⭐ 1,579 · Python · Apache-2.0 · last commit 2025-11-26**

### Repo/Folder Setup

Top-level structure ([root](https://github.com/web-arena-x/webarena)):

| Path | Purpose |
|---|---|
| [`browser_env/`](https://github.com/web-arena-x/webarena/tree/main/browser_env) | The Gym-style Playwright environment. `envs.py` (`ScriptBrowserEnv`), `async_envs.py`, `actions.py` (18-member `ActionTypes` enum + parsers), `processors.py` (accessibility-tree / HTML / image observation builders), `auto_login.py` (cookie minting), `env_config.py` (site URLs + hardcoded test accounts), `trajectory.py`, `helper_functions.py` (`RenderHelper`) |
| [`agent/`](https://github.com/web-arena-x/webarena/tree/main/agent) | `agent.py` defines `Agent`, `PromptAgent`, `TeacherForcingAgent`, `construct_agent()`. `agent/prompts/raw/*.py` holds five baseline prompts (CoT/direct × id-actree × 2-shot, plus a llama 3-shot variant); `agent/prompts/to_json.py` compiles them to `agent/prompts/jsons/` |
| [`evaluation_harness/`](https://github.com/web-arena-x/webarena/tree/main/evaluation_harness) | The scoring code — only two files: `evaluators.py` and `helper_functions.py` |
| [`config_files/`](https://github.com/web-arena-x/webarena/tree/main/config_files) | `test.raw.json` = all 812 task configs with `__SHOPPING__`-style URL placeholders; `examples/1..4.json` are hand-written samples |
| [`environment_docker/`](https://github.com/web-arena-x/webarena/tree/main/environment_docker) | README with the AMI/Docker hosting instructions + `webarena-homepage/app.py` (the Flask landing page on :4399) |
| [`llms/`](https://github.com/web-arena-x/webarena/tree/main/llms) | Thin provider layer: `providers/openai_utils.py` (chat/completion + exponential backoff), `providers/hf_utils.py`, `lm_config.py`, `tokenizers.py` |
| [`scripts/`](https://github.com/web-arena-x/webarena/tree/main/scripts) | `generate_test_data.py` (placeholder substitution), `check_error_runs.py`, `collect_obs.py`, `html2json.py`, `webarena-zeno.ipynb` |
| [`tests/`](https://github.com/web-arena-x/webarena/tree/main/tests) | pytest suite, see below |
| [`resources/`](https://github.com/web-arena-x/webarena/tree/main/resources) | README pointing at Google Drive dumps of execution traces + 179 human trajectories |

**Language / package manager:** Python 3.10 (`python_requires = >=3.7, <4` in `setup.cfg`), plain `pip` + `requirements.txt`, conda recommended for the env. Key pins: `playwright==1.32.1`, `openai==0.27.0` (legacy API — `openai.error.OpenAIError` is caught in `run.py:349`), `beartype==0.12.0`, `transformers==4.33.2`, `gymnasium`, `nltk`, `tiktoken`.

**Install:**
```bash
conda create -n webarena python=3.10; conda activate webarena
pip install -r requirements.txt
playwright install
pip install -e .
pip install -e ".[dev]"          # pre-commit, pytest, mypy, nbmake, pytest-asyncio
```

**Configuration — this is the heavy part.** [`browser_env/env_config.py:12-30`](https://github.com/web-arena-x/webarena/blob/main/browser_env/env_config.py) hard-asserts on import that all seven site env vars are set, so *nothing* imports without a hosted environment:

```bash
export SHOPPING="<host>:7770"        # Magento OneStopShop
export SHOPPING_ADMIN="<host>:7780/admin"
export REDDIT="<host>:9999"          # Postmill
export GITLAB="<host>:8023"
export MAP="<host>:3000"             # OpenStreetMap
export WIKIPEDIA="<host>:8888/wikipedia_en_all_maxi_2022-05/A/User:The_other_Kiwix_guy/Landing"
export HOMEPAGE="<host>:4399"
export OPENAI_API_KEY=sk-...
```
[`setup_env.sh`](https://github.com/web-arena-x/webarena/blob/main/setup_env.sh) does this given a single hostname. Site credentials are checked into `env_config.py` (`ACCOUNTS` dict — e.g. reddit `MarvelsGrantMan136/test1234`, gitlab `byteblaze/hello1234`).

**Hosted environment:** [`environment_docker/README.md`](https://github.com/web-arena-x/webarena/blob/main/environment_docker/README.md) recommends the public AMI `ami-08a862bf98e3bd7aa` (`webarena-with-configurable-map-backend`, us-east-2, t3a.xlarge + 1000 GB EBS), or individual Docker images per site (`shopping_final_0712`, `shopping_admin_final_0719`, `gitlab-populated-final-port8023`, `postmill-populated-exposed-withimg`, `kiwix33`). Env reset = stop/remove/re-run all containers; documented as required after each full 812-task sweep.

**Main entry points:**
- [`minimal_example.py`](https://github.com/web-arena-x/webarena/blob/main/minimal_example.py) — commented walkthrough of env setup/step against the demo sites.
- [`prepare.sh`](https://github.com/web-arena-x/webarena/blob/main/prepare.sh) → `python browser_env/auto_login.py` mints `.auth/*.json` cookie files (it logs in every 2-site combination, [`auto_login.py:113`](https://github.com/web-arena-x/webarena/blob/main/browser_env/auto_login.py)).
- `python scripts/generate_test_data.py` — expands `test.raw.json` into `config_files/0.json … 811.json`.
- [`run.py`](https://github.com/web-arena-x/webarena/blob/main/run.py) — the real entry point (see Evals).
- [`parallel_run.sh`](https://github.com/web-arena-x/webarena/blob/main/parallel_run.sh) — tmux-based 5-pane sharding of the 812 tasks with auto-restart on crash.

> ⚠️ The README carries a maintainer note (12/5/2024) recommending [AgentLab](https://github.com/ServiceNow/AgentLab)/[BrowserGym](https://github.com/ServiceNow/BrowserGym) over this repo for new experiments (parallel runs, unified leaderboard). This repo is positioned as the *canonical reproduction* implementation.

### Evals

**This repo is the eval.** There is no train loop.

- **Task set:** 812 tasks in [`config_files/test.raw.json`](https://github.com/web-arena-x/webarena/blob/main/config_files/test.raw.json), derived from 241 `intent_template_id`s. Distribution by site (computed from the file): shopping 187, shopping_admin 182, gitlab 180, map 109, reddit 106, gitlab+reddit 18, map+wikipedia 17, gitlab+wikipedia 6, reddit+shopping 5, map+shopping_admin 2. Each config carries `intent`, `start_url`, `require_login`, `storage_state`, `require_reset`, and an `eval` block.
- **Evaluator types** ([`evaluation_harness/evaluators.py`](https://github.com/web-arena-x/webarena/blob/main/evaluation_harness/evaluators.py)), dispatched by `evaluator_router()` at line 356 and combined by `EvaluatorComb` (line 336) — score is the **product** of all applicable evaluators, so it's all-or-nothing per task:
  - `StringEvaluator` (line 71) — `exact_match`, `must_include`, `fuzzy_match` (LLM-judged via `llm_fuzzy_match`, `helper_functions.py:146`), `ua_match` (LLM judge for unachievable tasks, line 176). Used by 325 tasks alone + 10 combined with URL.
  - `URLEvaluator` (line 173) — normalized URL + query-param set comparison. 66 alone, 129 with program_html.
  - `HTMLContentEvaluator` (line 244) — navigates to a `required_contents` locator and runs a Playwright/JS `locator` or a Python `func:` expression against live site state. 282 alone.
  - Site-specific state probes live in [`evaluation_harness/helper_functions.py`](https://github.com/web-arena-x/webarena/blob/main/evaluation_harness/helper_functions.py): `shopping_get_latest_order_url`, `shopping_get_sku_latest_review_author/_rating`, `reddit_get_post_url`, `gitlab_get_project_memeber_role`.
- **Metric:** binary per-task score → **average success rate**, printed by `run.py:365` (`Average score: ...`).
- **Reported baselines** ([paper](https://arxiv.org/abs/2307.13854)): **GPT-4 + CoT = 14.41%** end-to-end success rate; **human = 78.24%** (also recorded in [`resources/README.md`](https://github.com/web-arena-x/webarena/blob/main/resources/README.md) over the 179 recorded human trajectories). The README links a live [Google Sheets leaderboard](https://docs.google.com/spreadsheets/d/1M801lEpBbKSNwP-vDBkC_pF7LdyGU1f_ufZb_NWNBZQ/edit). Full trace dumps for text-bison-001, GPT-3.5-turbo-16k (direct/CoT, ±UA hint) and GPT-4+CoT are linked from `resources/README.md`.
- **Launching a run:**
  ```bash
  python run.py \
    --instruction_path agent/prompts/jsons/p_cot_id_actree_2s.json \
    --test_start_idx 0 --test_end_idx 812 \
    --model gpt-3.5-turbo \
    --result_dir <dir>
  ```
  Notable run-loop mechanics in [`run.py`](https://github.com/web-arena-x/webarena/blob/main/run.py): `--max_steps 30` default; `early_stop()` (line 161) also aborts after 3 consecutive parse failures or 3 repeated equivalent actions; cookies are re-minted per task in a subprocess before each config; each trajectory renders to `<result_dir>/<task_id>.html` plus an optional Playwright trace zip; `get_unfinished()` (line 393) makes reruns resumable.

### Test Cases

**Framework:** pytest (`pytest==7.1.2` in the `dev` extra), with `pytest-asyncio`; config in `setup.cfg`.

**Layout:** [`tests/conftest.py`](https://github.com/web-arena-x/webarena/blob/main/tests/conftest.py) + [`tests/test_browser_env/`](https://github.com/web-arena-x/webarena/tree/main/tests/test_browser_env) (5 files, 827 lines, **31 test functions**). `conftest.py` provides five function-scoped env fixtures (plain, current-viewport-only, accessibility-tree, accessibility-tree+viewport, and an autouse async one) that all guarantee `env.close()`.

**Categories:**
1. *Pure unit* — [`test_actions.py`](https://github.com/web-arena-x/webarena/blob/main/tests/test_browser_env/test_actions.py) (2 tests). `test_is_equivalent` is the interesting one: it loops over every member of `ActionTypes`, generates random action pairs, and `match`es per type to assert exactly which fields drive equivalence (coords for mouse actions, `text` for typing, `element_id`/`element_role`+`element_name`/`pw_code` fallback chain for click/hover/type). This directly guards the repeated-action early-stop logic in `run.py`.
2. *Live-browser action functionality* — [`test_action_functionalities.py`](https://github.com/web-arena-x/webarena/blob/main/tests/test_browser_env/test_action_functionalities.py) (13 tests, 331 lines): `test_id_click`, `test_id_hover`, `test_id_type`, `test_id_delete_input`, `test_key_press`, `test_scroll`, `test_inter_page_actions`, `test_e2e_id_based_actions`, `test_frame_locator`, `test_xpath`.
3. *Observation-space* — [`test_script_browser_env.py`](https://github.com/web-arena-x/webarena/blob/main/tests/test_browser_env/test_script_browser_env.py) (9 tests): `test_accessibility_tree`, `test_accessibility_tree_viewport`, `test_accessibility_tree_observation_update`, `test_html_current_viewport`, `test_focus_placeholder_and_label`, `test_observation_tab_information`, plus an `@pytest.mark.asyncio` async-env test.
4. *Auth* — [`test_auth_cookie.py`](https://github.com/web-arena-x/webarena/blob/main/tests/test_browser_env/test_auth_cookie.py) (2 tests, sync + async) verifying the minted cookie files actually log in.
5. *Raw Playwright sanity* — [`test_playwright_actions.py`](https://github.com/web-arena-x/webarena/blob/main/tests/test_browser_env/test_playwright_actions.py) (5 tests).

**Skips:** 3 tests are `@pytest.mark.skip` — `test_hover`/`test_select_option` in `test_playwright_actions.py` ("not important, but the site is flaky") and `test_parallel_script_browser_env` ("Gym doesn't support self-defined observations").

**CI:** two workflows.
- [`.github/workflows/tests.yml`](https://github.com/web-arena-x/webarena/blob/main/.github/workflows/tests.yml) — on every push: Python 3.10.9, install reqs, `playwright install`, NLTK data, then **`mypy --strict .`** (excluding `scripts`) followed by `pytest`. Note the README tells users to add their own site URLs to this workflow's env block; the checked-in workflow currently defines **no** env vars, so the browser tests that need a hosted WebArena instance can't pass as-is on a fork.
- [`.github/workflows/pre-commit.yml`](https://github.com/web-arena-x/webarena/blob/main/.github/workflows/pre-commit.yml) — runs `pre-commit` (black @79 cols, isort, nbstripout, whitespace/yaml/large-file hooks per `.pre-commit-config.yaml`).

The codebase is type-checked end-to-end: `mypy` strict mode plus runtime `@beartype` decorators on the evaluator and action APIs.

---

## Mind2Web

> Dataset + fine-tuning/eval code for the first generalist web-agent benchmark: 2,350 open-ended tasks over 137 real websites in 31 domains, evaluated **offline** against recorded HTML snapshots (no live browser).
> **⭐ 1,018 · Jupyter Notebook (by bytes; effectively Python) · MIT · last commit 2025-11-04**

### Repo/Folder Setup

The repo is small — **31 tracked files**, all under `src/` plus a README and a notebook:

| Path | Purpose |
|---|---|
| [`src/candidate_generation/`](https://github.com/OSU-NLP-Group/Mind2Web/tree/main/src/candidate_generation) | Stage 1 — a DeBERTa-v3 cross-encoder that ranks HTML elements. `model.py` (`CrossEncoder`), `train.py`, `evaluate.py`, `metric.py` (`CERerankingEvaluator`), `dataloader.py`, `conf/{config,model/deberta-v3-base}.yaml` |
| [`src/action_prediction/`](https://github.com/OSU-NLP-Group/Mind2Web/tree/main/src/action_prediction) | Stage 2 — MindAct. `train.py`, `evaluate.py` (local HF models), `evaluate_llm.py` (OpenAI), `metric.py` (`ActionEvaluatorMultiChoice`, `ActionEvaluatorGeneration`), `dataloader.py` (`MultiChoiceDataset`, `format_input_multichoice`), `llm_prompt.json` (the 3-shot prompt), `conf/model/{t5-base,flan-t5-base,flan-t5-large,flan-t5-xl}.yaml` |
| [`src/data_utils/`](https://github.com/OSU-NLP-Group/Mind2Web/tree/main/src/data_utils) | `dom_utils.py` (`build_dom_tree`, `clean_tree`, `prune_tree`, `get_tree_repr`) and `process_trace.py` / `process_snapshots.ipynb` for extracting raw HTML from Playwright traces |
| [`data_inspector.ipynb`](https://github.com/OSU-NLP-Group/Mind2Web/blob/main/data_inspector.ipynb) | 18 MB notebook demonstrating how to inspect the raw dump |

**Language / package manager:** Python + `pip install -r requirements.txt` (fully pinned, ~70 deps): `torch==2.0.1`, `transformers==4.29.2`, `sentence-transformers==2.2.2`, `hydra-core==1.3.2`, `datasets==2.14.4`, `openai==0.28.0`, `peft`, `optimum`, `lxml`.

**Configuration:** [Hydra](https://hydra.cc/) YAML, not CLI flags. You must hand-edit [`src/action_prediction/conf/config.yaml`](https://github.com/OSU-NLP-Group/Mind2Web/blob/main/src/action_prediction/conf/config.yaml) to replace the literal placeholders `DATA_PATH`, `CANDIDATE_SCORE_FILE_PATH`, and `LOG_FILE_PATH`. For LLM eval, `export OPENAI_API_KEY=...` (read in `evaluate_llm.py:44`). No browser driver, no Docker, no hosted environment — everything runs against static JSON.

**Data acquisition:** train split from [🤗 osunlp/Mind2Web](https://huggingface.co/datasets/osunlp/Mind2Web); the **test splits are shipped as a password-protected zip (password `mind2web`)** deliberately, to resist LLM crawlers. The README embeds BIG-bench-style canary GUIDs. Optional raw dump (Playwright traces, HAR, videos, MHTML snapshots) is distributed over Globus/OSC, not GitHub.

**Main entry points** (run from `src/`):
```bash
python candidate_generation/train.py model=deberta-v3-base
python candidate_generation/evaluate.py --model_path ... --data_path ... --split_file 'data/test_website/*.json' --output_dir ...
torchrun --nproc-per-node 4 action_prediction/train.py model=flan-t5-large train.fsdp=True ...
python action_prediction/evaluate.py +model_path=... model=flan-t5-large +output_path=... +top_k=50
python action_prediction/evaluate_llm.py +output_path=... +llm_prompt=action_prediction/llm_prompt.json +llm=gpt-3.5-turbo +llm_rate_limit=60 +top_k=50
```

### Evals

**Task sets / splits** (README "Data Splits"):

| Split | Instances | Generalization tested |
|---|---|---|
| train | 1,009 | — |
| test_task (Cross-Task) | 252 | new tasks, seen websites |
| test_website (Cross-Website) | 177 | unseen websites, seen domains |
| test_domain (Cross-Domain) | 912 | unseen domains |

Dataset totals: 2,350 tasks, 137 websites, 31 domains, ~7.3 steps/task, ~1,135 elements/page.

**Metrics** — all defined in [`src/action_prediction/metric.py`](https://github.com/OSU-NLP-Group/Mind2Web/blob/main/src/action_prediction/metric.py):
- `element_acc` — predicted element ∈ `pos_candidates` (line 222).
- `action_f1` — token-level F1 between predicted and gold operation string (`calculate_f1`, line 65), covering `CLICK` / `TYPE <value>` / `SELECT <value>`.
- `step_acc` (Step SR) — `1 if (action_f1 == 1 and element_acc == 1)` (line 228).
- `marco_element_acc` / `marco_action_f1` / `marco_step_acc` — **macro** averages, grouped by `annotation_id` (lines 237-259). ⚠️ The README's 2023-10-30 update explicitly says the paper reports macro; the original repo only had micro, which biases toward long tasks. Use `marco_*` for paper comparisons. (The `marco` spelling is the actual key in the output JSON.)
- Also emitted: `error_ratio` (distribution of per-task failed-step counts) and `acc_per_website`.
- Candidate generation ([`src/candidate_generation/metric.py`](https://github.com/OSU-NLP-Group/Mind2Web/blob/main/src/candidate_generation/metric.py)) reports `mrr`, `acc`, and `recall@{3,5,10,20,50,100}`.
- **Task success rate (SR)** — the paper's SR (all steps correct) is *not* computed by this repo's metric code; only per-step metrics and `error_ratio` are.

**Reported baselines** ([paper](https://arxiv.org/abs/2306.06070), Table 2 — Ele.Acc / Op.F1 / Step SR / SR):

| Model | Cross-Task | Cross-Website | Cross-Domain |
|---|---|---|---|
| Classification (DeBERTa) | 26.8 Ele.Acc | 21.6 | 24.5 |
| Generation (Flan-T5-B, no candidates) | 20.2 / 52.0 / 17.5 / 0.0 | 13.9 / 44.7 / 11.0 / 0.0 | 14.2 / 44.7 / 11.9 / 0.4 |
| MindAct Flan-T5-Base | 43.6 / 76.8 / 41.0 / 4.0 | 32.1 / 67.6 / 29.5 / 1.7 | 33.9 / 67.3 / 31.6 / 1.6 |
| MindAct Flan-T5-Large | 53.4 / 75.7 / 50.3 / 7.1 | 39.2 / 67.1 / 35.3 / 1.1 | 39.7 / 67.2 / 37.3 / 2.7 |
| MindAct Flan-T5-XL | **55.1 / 75.7 / 52.0 / 5.2** | **42.0 / 65.2 / 38.9 / 5.1** | **42.1 / 66.5 / 39.6 / 2.9** |
| GPT-3.5-Turbo (3-shot, top-50) | 20.3 / 56.6 / 17.4 / 0.8 | 19.3 / 48.8 / 16.2 / 0.6 | 21.6 / 52.8 / 18.6 / 1.0 |
| GPT-4 (3-shot, top-10, 50-task subset) | 41.6 / 60.6 / 36.2 / 2.0 | 35.8 / 51.1 / 30.1 / 2.0 | 37.1 / 46.5 / 26.4 / 2.0 |

Candidate generation (DeBERTa-v3-base): **Recall@50 = 88.9 / 85.3 / 85.7** across the three splits; the released `scores.pkl` artifacts are stated as ~85% Recall@50.

**How a run is launched:** see the entry-point commands above. `evaluate.py`/`evaluate_llm.py` iterate `cfg.data.test_split_files` (all three test splits by default) and write `{split}_outputs_top{k}.json`, `{split}_predictions_top{k}.json`, `{split}_results_top{k}.json` to `output_path` ([`metric.py:277-283`](https://github.com/OSU-NLP-Group/Mind2Web/blob/main/src/action_prediction/metric.py)). Custom models plug in by exposing a `generate(prompt, ...)` method (the README points at `metric.py:328`).

### Test Cases

**None.** There is no `tests/` directory, no `conftest.py`, no `pytest.ini`/`setup.cfg`/`pyproject.toml`, and no `.github/` directory at all — so **zero programmatic tests and zero CI**. The only executable verification artifacts are the two notebooks (`data_inspector.ipynb`, `src/data_utils/process_snapshots.ipynb`), which are illustrative rather than assertive. Correctness rests entirely on the eval metrics above.

---

## WebShop

> A simulated e-commerce site (1.18 M real Amazon products, 12,087 crowdsourced instructions) served by Flask, exposed both as a browsable website and as an OpenAI-Gym text environment, with rule/IL/RL baselines and sim-to-real transfer code for Amazon & eBay.
> **⭐ 583 · Python · MIT · last commit 2024-09-05**

### Repo/Folder Setup

| Path | Purpose |
|---|---|
| [`web_agent_site/`](https://github.com/princeton-nlp/WebShop/tree/master/web_agent_site) | The environment. `app.py` (Flask site on :3000), `engine/engine.py` (product loading + page rendering), `engine/goal.py` (**the reward function**), `engine/normalize.py` (color/size normalization), `envs/web_agent_text_env.py` (`WebAgentTextEnv`, "simple" mode, in-process `SimServer`/`SimBrowser`), `envs/web_agent_site_env.py` (`WebAgentSiteEnv`, Selenium/Chromedriver against the real Flask site), `models/models.py` (`RandomPolicy` etc.), `templates/*.html` (8 page templates), `utils.py` |
| [`baseline_models/`](https://github.com/princeton-nlp/WebShop/tree/master/baseline_models) | Paper baselines: `train_search_il.py` (BART query generator), `train_choice_il.py` (BERT choice model), `train_rl.py` (A2C-style RL), `test.py` (the eval driver), `agent.py`, `env.py` (`WebEnv` split wrapper), `models/{bert,rnn,modules}.py`, `generate_search.py` |
| [`search_engine/`](https://github.com/princeton-nlp/WebShop/tree/master/search_engine) | Pyserini/Lucene BM25 index build: `convert_product_file_format.py`, `run_indexing.sh` (builds `indexes`, `indexes_100`, `indexes_1k`, `indexes_100k`), `lucene_searcher.py` |
| [`transfer/`](https://github.com/princeton-nlp/WebShop/tree/master/transfer) | Sim-to-real: `app.py` (Gradio demo), `predict_help.py` (Amazon/eBay scrapers + `Page` enum), `webshop_lite.py` (condensed templating engine) |
| [`run_envs/`](https://github.com/princeton-nlp/WebShop/tree/master/run_envs) | `run_web_agent_text_env.py` / `run_web_agent_site_env.py` — `RandomPolicy` demos of each env |
| [`tests/`](https://github.com/princeton-nlp/WebShop/tree/master/tests) | pytest suite mirroring `web_agent_site/` and `transfer/` |

**Language / package manager:** Python 3.8.13 + conda; `pip install -r requirements.txt` driven by `setup.sh`. Requires **Java** (Pyserini/Lucene) and, for `html` mode, **ChromeDriver** placed at `web_agent_site/envs/chromedriver`. Pins: `gym==0.24.0`, `Flask==2.1.2`, `torch==1.11.0`, `transformers==4.19.2`, `pyserini==0.17.0`, `spacy==3.3.0`, `selenium==4.2.0`, `gradio`, `pytest`, `requests_mock`. An ARM-Mac path exists (`setup_arm.sh`, `requirements_arm.txt`, `README_INSTALL_ARM-MAC.md`). Also on PyPI as `webshop`.

**Install:**
```bash
conda create -n webshop python=3.8.13 && conda activate webshop
./setup.sh -d small      # or -d all for the full 1.18M-product dump
```
[`setup.sh`](https://github.com/princeton-nlp/WebShop/blob/master/setup.sh) installs deps, `conda install faiss-cpu` + `openjdk=11`, `gdown`s the product/attribute/instruction JSONs into `data/`, downloads `spacy en_core_web_lg`, builds the four Lucene indexes, and pulls 50 sample human trajectories into `user_session_logs/`. No API keys and no env vars are needed — the environment is fully local. To move from the 1,000-product preview to the full catalog you edit `DEFAULT_ATTR_PATH` / `DEFAULT_FILE_PATH` in [`web_agent_site/utils.py:10-11`](https://github.com/princeton-nlp/WebShop/blob/master/web_agent_site/utils.py). Optional: ResNet image features (`feat_conv.pt`, `feat_ids.pt`) and the full human demonstration set, both from Google Drive.

**Main entry points:**
- `./run_dev.sh` → `python -m web_agent_site.app --log --attrs` → browsable site at `http://localhost:3000/<session_id>`; `--log` writes per-session `.jsonl` trajectories to `user_session_logs/mturk/`. `./run_prod.sh` is the same without `--attrs`.
- Gym: `gym.make('WebAgentTextEnv-v0', observation_mode='text', num_products=...)` — registered in [`web_agent_site/envs/__init__.py`](https://github.com/princeton-nlp/WebShop/blob/master/web_agent_site/envs/__init__.py) alongside `WebAgentSiteEnv-v0`. Action space is textual: `search[...]` / `click[...]`.
- `./run_web_agent_text_env.sh`, `./run_web_agent_site_env.sh` — random-policy smoke runs.
- `python baseline_models/test.py` — the baseline eval driver.
- `python transfer/app.py` — local Gradio sim-to-real demo (also a [🤗 Space](https://huggingface.co/spaces/webshop/amazon_shop)).

### Evals

- **Task set:** 12,087 crowdsourced instructions, split **10,587 train / 1,000 dev / 500 test**. The split is index-based in [`baseline_models/env.py:28-33`](https://github.com/princeton-nlp/WebShop/blob/master/baseline_models/env.py): `test = range(500)`, `eval(dev) = range(500, 1500)`, `train = range(1500, len(goals))`.
- **Metrics** — the reward is *dense*, computed in [`web_agent_site/engine/goal.py:228`](https://github.com/princeton-nlp/WebShop/blob/master/web_agent_site/engine/goal.py):
  ```
  reward = r_type × (num_attr_matches + num_option_matches + r_price) / (|attributes| + |goal_options| + 1)
  ```
  where `r_type ∈ {0.0, 0.1, 0.5, 1.0}` comes from `get_type_reward` (query match, category match, and a fuzzy title-similarity score), `r_price` is a price-ceiling indicator, and attribute/option matches are counted by `get_attribute_reward` / `get_option_reward`.
  - **Task Score** = 100 × average reward.
  - **Success Rate** = fraction of episodes with reward == 1.0 (`test.py:135` counts `s == 10.0` on the env's 0-10 scale; the comment at line 130 notes "env score is 0-10, paper is 0-100").
- **Where eval code lives:** reward logic in `web_agent_site/engine/goal.py`; the eval driver is [`baseline_models/test.py`](https://github.com/princeton-nlp/WebShop/blob/master/baseline_models/test.py), which runs 500 episodes (`for i in range(500)`), capped at 100 steps each, scoring the learned model *and* the rule baseline side by side each episode.
- **Reported baselines** ([paper](https://arxiv.org/abs/2207.01206), Task Score / Success Rate):

  | Method | Task Score | Success Rate |
  |---|---|---|
  | Rule heuristic | 45.6 | 9.6% |
  | IL | 59.9 | 29.1% |
  | IL + RL | 62.4 | 28.7% |
  | Human expert | 82.1 | 59.6% |

  The paper also reports non-trivial sim-to-real transfer to Amazon and eBay. Trained checkpoints (choice IL, search IL) are on Google Drive; agents also on the [🤗 webshop org](https://huggingface.co/webshop).
- **Launching an eval run:**
  ```bash
  cd baseline_models
  pip install -r requirements.txt
  python test.py --model_path ./ckpts/web_click/epoch_9/model.pth \
                 --bart_path ./ckpts/web_search/checkpoint-800
  ```
  Flags worth noting: `--softmax 0` forces greedy (deterministic but worse) choice selection; `--bart 0` uses the raw instruction as the search query; `--mem 1` enables observation/action history. The rule baseline is deterministic; model results vary run-to-run under softmax sampling.

### Test Cases

**Framework:** pytest (in `requirements.txt`), plus `requests_mock` for HTTP stubbing. An **empty** `conftest.py` sits at the repo root purely to put the root on `sys.path`.

**Layout** — [`tests/`](https://github.com/princeton-nlp/WebShop/tree/master/tests), 4 files / 767 lines / **17 test functions**, mirroring the source tree:
```
tests/
├── web-agent-site/
│   ├── test_utils.py                 (3 tests)
│   └── engine/
│       ├── test_goal.py              (4 tests, 199 lines)
│       └── test_normalize.py         (2 tests)
└── transfer/
    ├── mocks/                        (8 recorded HTML fixtures)
    └── test_predict_help.py          (7 tests, 467 lines)
```

**Categories:**
1. **Reward-function unit tests** — [`tests/web-agent-site/engine/test_goal.py`](https://github.com/princeton-nlp/WebShop/blob/master/tests/web-agent-site/engine/test_goal.py) is the most interesting file in the repo's test suite: `test_get_type_reward`, `test_get_attribute_reward`, `test_get_option_reward`, `test_get_reward`. It pins down subtle fuzzy-matching behavior with real product titles and `math.isclose` tolerances — e.g. asserting that out-of-order category paths (`"b › c › a"` vs `"a › b › c"`) still count as a category match, that `"a › a › d"` does not, and that a basketball-shoe title pair scores `title_score ≈ 0.333` while two unrelated products score `< 0.05`. Because the headline metric *is* this reward, these tests are effectively the benchmark's correctness guarantee.
2. **Text normalization** — `test_normalize_color`, `test_normalize_color_size`.
3. **Utilities** — `test_random_idx` (the weighted-sampling `bisect` helper), `test_setup_logger`, `test_generate_mturk_code` (SHA1 → 10-char redeem code).
4. **Sim-to-real scraper tests** — [`tests/transfer/test_predict_help.py`](https://github.com/princeton-nlp/WebShop/blob/master/tests/transfer/test_predict_help.py) uses `@requests_mock.Mocker` with 8 checked-in raw HTML fixtures under `tests/transfer/mocks/` (`mock_parse_item_page_{ws,ws_desc,ws_feat,amz,ebay}`, `mock_parse_results_{ws,amz,ebay}`) to test `parse_item_page_*` / `parse_results_*` for WebShop, Amazon and eBay without network access, plus `test_convert_dict_to_actions`. This is a genuinely good pattern for scraper-based agents: real-page snapshots frozen as fixtures.

**Not tested:** the Gym envs themselves, the Flask routes, and the baseline models. `run_envs/run_web_agent_text_env.py:4` even carries a `TODO: move to testing dir for more rigorous tests`.

**CI:** one workflow, [`.github/workflows/pytest.yml`](https://github.com/princeton-nlp/WebShop/blob/master/.github/workflows/pytest.yml) — on push/PR to `master`, Python 3.8, 10-minute timeout, `pip install -r requirements.txt` + `spacy download en_core_web_lg`, then `pytest -v`. Notably it does **not** run `setup.sh`, so no product data, no Java, and no Lucene index exist in CI — which is exactly why the suite is scoped to pure functions and mocked HTTP. The badge is in the README. The repo also ships `.github/ISSUE_TEMPLATE.md` and `.github/PULL_REQUEST_TEMPLATE.md`.

---

## WebLINX

> Benchmark + Python library for *conversational* web navigation: 2,337 expert demonstrations (~100 K interactions) of multi-turn user↔agent dialogue over 155 real websites, with a two-stage baseline (DMR element ranker → action model) and an in-repo leaderboard. ICML 2024 Spotlight.
> **⭐ 163 · Python · Apache-2.0 · last commit 2026-08-16**

### Repo/Folder Setup

| Path | Purpose |
|---|---|
| [`weblinx/`](https://github.com/McGill-NLP/weblinx/tree/main/weblinx) | The pip-installable library. `__init__.py` defines the core abstractions — `Demonstration` (line 38), `Turn` (line 306, a `dict` subclass), `Replay` (line 1003), plus `list_demonstrations`, `filter_turns`, `load_demos_in_split`. `_data/splits.json` ships the official split membership |
| [`weblinx/eval/`](https://github.com/McGill-NLP/weblinx/tree/main/weblinx/eval) | `metrics.py` (metric classes), `__init__.py` (`run_evaluation`, `process_model_results`, `compute_aggregated_scores`, `auto_eval_and_save`, `validate_reference_action`), `__main__.py` (the `python -m weblinx.eval` CLI) |
| [`weblinx/processing/`](https://github.com/McGill-NLP/weblinx/tree/main/weblinx/processing) | `dom.py`, `intent.py` (the `Intent` dataclass — 14 intents), `outputs.py` (parsing model output strings back into actions), `prompt.py`, `truncation.py` |
| [`weblinx/utils/`](https://github.com/McGill-NLP/weblinx/tree/main/weblinx/utils) | `envs.py`, `format.py`, `html.py`, `hydra.py`, `recs.py`, `url.py`, `video.py` |
| [`modeling/`](https://github.com/McGill-NLP/weblinx/tree/main/modeling) | **Repo-level, not part of the package** — training/eval for each baseline family: `dmr/`, `llama/`, `flan/` (also hosts MindAct variants), `pix2act/`, `reranking/`. Each has `train.py`, `eval.py`, `processing.py` and a hydra `conf/` with `variant/*.yaml` |
| [`tests/`](https://github.com/McGill-NLP/weblinx/tree/main/tests) | unittest suite (see below) |
| [`docs/`](https://github.com/McGill-NLP/weblinx/tree/main/docs) | Jekyll site (`_docs/`, `_pages/leaderboard.md`, `_sass/`, `scripts/`) published to GitHub Pages |
| [`examples/`](https://github.com/McGill-NLP/weblinx/tree/main/examples) | `WebLINX_Colab_Notebook.ipynb` |

**Language / package manager:** Python ≥3.8, setuptools (`setup.py`), published to PyPI as [`weblinx`](https://pypi.org/project/weblinx/). The base package has a single dependency (`tqdm`); everything else is an extra:
```bash
pip install weblinx            # base
pip install weblinx[all]       # everything
pip install weblinx[processing]  # lxml
pip install weblinx[video]       # opencv-python-headless, numpy, Pillow
pip install weblinx[eval]        # sacrebleu, numpy, pandas, tqdm
pip install weblinx[dev]         # black, wheel
```
The `modeling/` code has its own heavier [`modeling/requirements.txt`](https://github.com/McGill-NLP/weblinx/blob/main/modeling/requirements.txt) plus a manual post-install of `flash-attn>=2.3.0` (documented with three fallback invocations for low-RAM / nvcc-trouble machines).

**Configuration:** `export WEBLINX_PROJECT_DIR=$(pwd)` (from `modeling/`) plus hydra configs under `modeling/*/conf/`. Data comes from Hugging Face via `snapshot_download(repo_id="McGill-NLP/WebLINX-full", repo_type="dataset", local_dir="./wl_data/")`; configs default to `${project_dir}/wl_data/demonstrations/` and `./wl_data/candidates/train.jsonl`, with symlinking documented for split disks. **No browser driver, no API keys, no Docker** — evaluation is fully offline against recorded demonstrations. Pix2Act additionally needs `Arial.TTF` at `modeling/fonts/Arial.TTF`.

**Main entry points:**
```bash
python -m dmr.train                       # train the Dense Markup Ranker
python -m dmr.eval eval.split=test_iid,test_web,test_geo,test_cat,test_vis
python -m llama.train +variant="ft_1.3b"  # or ft_2.7b / ft_7b / ft_13b / ft_llama3_8b_instruct via accelerate+FSDP
python -m llama.eval -m +variant="ft_2.7b" eval.split=valid,test_iid,test_web,test_geo,test_cat,test_vis
python -m weblinx.eval -d results -b ./wl_data/demonstrations   # score everything
```
Also `flan.train`/`flan.eval` (Flan-T5 and MindAct variants) and `pix2act.train`/`pix2act.eval`.

> Note: WebLINX is also available through [BrowserGym](https://github.com/ServiceNow/BrowserGym) via the `weblinx-browsergym` PyPI extension and the [WebLINX-1.1 dataset](https://huggingface.co/datasets/McGill-NLP/weblinx-browsergym), which changes which steps are evaluated (adds tab actions). Results from that path must be labeled "WebLINX-1.1"/"WebLINX-BG" to distinguish them from v1.0 numbers.

### Evals

**Splits** — exact counts from the shipped [`weblinx/_data/splits.json`](https://github.com/McGill-NLP/weblinx/blob/main/weblinx/_data/splits.json) (demonstrations per split):

| Split | Demos | Tests generalization to |
|---|---|---|
| `train` | 969 | — |
| `valid` | 100 | hyperparameter selection |
| `dev` | 200 | — |
| `test_iid` | 100 | in-domain |
| `test_web` | 211 | unseen websites (same subcategory) |
| `test_geo` | 290 | unseen geographic regions |
| `test_cat` | 223 | unseen subcategories |
| `test_vis` | 444 | instructor without screen visibility |

Total 2,337 demonstrations, 155 websites, 8 categories / 50 subcategories, >100 K interactions, ~43 turns/demo.

**Metrics** — [`weblinx/eval/metrics.py`](https://github.com/McGill-NLP/weblinx/blob/main/weblinx/eval/metrics.py) defines an abstract `Metric` with `score()` + `is_applicable()`, then:
- `IntentMatchMetric` (IM) — binary intent equality; always applicable.
- `IOUMetric` — bounding-box intersection-over-union between predicted and reference elements (applies to `click`, `submit`, `textinput`, `change`, `hover`, `scroll`, `copy`, `paste`).
- `ChrFMetric` — `sacrebleu.sentence_chrf`, normalized to [0,1], for text arguments (`say`, `textinput`, `load`, `change`).
- `URLFMetric` — character-F over URL components for `load`.
- `ExactMatchMetric`.

The intent→metric map lives in [`weblinx/eval/__init__.py:252-259`](https://github.com/McGill-NLP/weblinx/blob/main/weblinx/eval/__init__.py); `compute_overall_score` (line 219) multiplies where both apply (`textinput` = IoU × chrF), and unmatched intents are zeroed (line 296). Both a **conditional** score and an **unconditional_score** are emitted. `validate_reference_action` (line 83) encodes the turn-filtering rules — e.g. a `click` that leads to a `copy` is skipped, and a `click` followed by a `submit` with the same uid is dropped. The DMR ranker is scored separately with `recall_at_k` and `mean_reciprocal_rank` ([`modeling/dmr/eval.py:20,34`](https://github.com/McGill-NLP/weblinx/blob/main/modeling/dmr/eval.py)).

**Reported baselines** — the repo hosts its own leaderboard at [`docs/_pages/leaderboard.md`](https://github.com/McGill-NLP/weblinx/blob/main/docs/_pages/leaderboard.md) (test-OOD averages; Overall / IM / Element-IoU / Text-F1):

| Model | Overall | IM | Element (IoU) | Text (F1) | Finetuned |
|---|---|---|---|---|---|
| Llama-3-8B-Web | **28.88** | 84.36 | 27.44 | 28.88 | ✔ |
| Llama-2-13B | 25.21 | 81.91 | 22.82 | 26.60 | ✔ |
| S-LLaMA-2.7B | 25.02 | 84.00 | 22.60 | 27.17 | ✔ |
| Llama-2-7B | 24.57 | 82.64 | 22.26 | 26.50 | ✔ |
| Flan-T5-3B | 23.77 | 81.14 | 20.31 | 25.75 | ✔ |
| S-LLaMA-1.3B | 23.73 | 83.32 | 20.54 | 25.85 | ✔ |
| GPT-3.5 (finetuned) | 21.22 | 77.56 | 18.64 | 22.39 | ✔ |
| MindAct-3B | 20.94 | 79.89 | 16.50 | 23.16 | ✔ |
| Fuyu-8B | 19.97 | 80.07 | 15.70 | 22.30 | ✔ |
| Pix2Act-1.3B | 16.88 | 81.80 | 8.28 | 25.21 | ✔ |
| GPT-4T (zero-shot) | 10.72 | 41.66 | 10.85 | 6.75 | ❌ |
| GPT-4V (zero-shot) | 10.45 | 42.36 | 10.91 | 6.21 | ❌ |
| GPT-3.5T (zero-shot) | 8.51 | 42.77 | 8.62 | 3.45 | ❌ |
| Llama-2-13B (zero-shot) | 5.16 | 43.68 | 4.80 | 1.31 | ❌ |

DMR leaderboard (recall@10 by split — Test-Vis / Test-Geo / Test-Cat / Test-Web / Test-OOD): MiniLM 59.73 / 50.95 / 44.05 / 52.75 / **51.87**; BGE 60.07 / 48.82 / 43.61 / 47.55 / 50.01; GTE 56.91 / 44.46 / 42.74 / 48.39 / 48.16. The headline finding: finetuned small text-only models beat zero-shot GPT-4V by ~2.5×, but **all** models degrade sharply on unseen subcategories (`test_cat`).

**Launching an eval run:**
```bash
# 1. produce model outputs per split
python -m llama.eval -m +variant="ft_2.7b" eval.split=valid,test_iid,test_web,test_geo,test_cat,test_vis
# 2. score them
python -m weblinx.eval -d results -b ./wl_data/demonstrations
```
`weblinx.eval.__main__` defaults to `--splits valid,test_iid,test_vis,test_geo,test_web,test_cat`, supports `--skip-eval` (aggregate only) and `--skip-hashes`, and writes `results/aggregated_scores.json` with one record per (split, intent, metric, model_name, project_name) including `score` and `unconditional_score`. A demo-level cache is built at `./.cache/demonstrations` because the first pass loads millions of files.

### Test Cases

**Framework:** stdlib `unittest` (not pytest) — `python -m unittest discover tests`.

**Layout** — [`tests/`](https://github.com/McGill-NLP/weblinx/tree/main/tests): 3 test modules, 4 test classes, **7 test methods**, plus `tests/README.md`, `tests/requirements.txt` (`-e .[eval,dev,processing]`, `ujson`, `orjson`) and `tests/demonstrations/candidates_unittest.jsonl`.

**Categories:**
1. **Core data-model tests** — [`tests/test_demonstration.py`](https://github.com/McGill-NLP/weblinx/blob/main/tests/test_demonstration.py) (5 tests): `test_format_repr`; `test_validate_json_backend_valid`/`_invalid` (`unittest.mock.patch` on `importlib.util.find_spec` to simulate presence/absence of the `orjson`/`ujson` backends — a nice, dependency-free way to test optional-dep handling); `test_repr`; `test_is_valid` (all required demo files present); `test_get_version` (returns `(1,0,0)` or `"1.0.0"`).
2. **Prompt-processing test** — [`tests/test_processing_prompt.py`](https://github.com/McGill-NLP/weblinx/blob/main/tests/test_processing_prompt.py): `test_find_turns_with_instructor_chat` loads the real demonstration `aaabtsd`, builds a `Replay`, takes turn 15, and asserts the helper returns exactly the 3 prior instructor turns — then cross-checks against an equivalent inline `filter()` and asserts list equality. A good oracle-by-reimplementation pattern.
3. **Modeling-integration test** — [`tests/test_build_prompt_records.py`](https://github.com/McGill-NLP/weblinx/blob/main/tests/test_build_prompt_records.py) imports from `modeling.llama.processing` (so it spans the library/modeling boundary) and loads candidates from `tests/demonstrations/candidates_unittest.jsonl`. ⚠️ **`test_format_candidates` has a docstring and no body** — it is an empty placeholder that always passes. The file also carries a commented-in helper, `create_candidates_unittest_jsonl()`, documenting how the fixture was generated from `wl_data/candidates/test_geo.jsonl`.

**Notably not tested:** `weblinx/eval/metrics.py` (IoU, chrF, URLF, the intent→metric map, `compute_overall_score`) has **no unit tests**, despite being the code that produces every leaderboard number. Same for `weblinx/processing/outputs.py` (model-output parsing) and `weblinx/processing/truncation.py`.

**CI** — three workflows:
- [`.github/workflows/run-tests.yml`](https://github.com/McGill-NLP/weblinx/blob/main/.github/workflows/run-tests.yml) — on push/PR to `main`: Python 3.9, pip cache, then **downloads two real demonstrations** (`aaabtsd.zip`, `aajfwoq.zip`) from the `tests-assets` GitHub release into `tests/demonstrations/` (cached by `github.sha`), then `python -m unittest discover -s tests`. Fetching real fixture data from a release tag is a clean way to keep multi-MB demonstrations out of the repo while keeping tests hermetic-ish.
- [`.github/workflows/publish-python.yml`](https://github.com/McGill-NLP/weblinx/blob/main/.github/workflows/publish-python.yml) — on GitHub release: rewrites `weblinx/version.py` from the release tag via `.github/scripts/python/update_version.py`, builds sdist+wheel, publishes to PyPI with trusted publishing (`id-token: write`, no stored token).
- [`.github/workflows/jekyll-gh-pages.yml`](https://github.com/McGill-NLP/weblinx/blob/main/.github/workflows/jekyll-gh-pages.yml) — builds and deploys `docs/` (including the leaderboard) to GitHub Pages on push to `main`. New leaderboard entries arrive as PRs editing `docs/_pages/leaderboard.md`.

---

## Cross-Repo Observations

**Environment fidelity vs. reproducibility is the axis these four split on.** WebArena and WebShop run *live* (Playwright against Dockerized real apps; Selenium/Flask against a simulated store) and measure end-to-end task success; Mind2Web and WebLINX replay *recorded* HTML/DOM and measure per-step action agreement. The live pair needs infrastructure (an AMI, Java + Lucene, cookie minting, env resets between sweeps); the offline pair needs only a dataset download and GPUs, which is why their metric surface is richer (element accuracy, IoU, chrF) but their scores don't answer "did the task get done."

**Evaluator design worth stealing.** WebArena's `EvaluatorComb` multiplying independent evaluators (string / URL / live-DOM-probe) makes tasks all-or-nothing and lets a task assert on *post-hoc server state* (`shopping_get_latest_order_url`, `gitlab_get_project_memeber_role`) rather than just the final page — the most transferable idea in the batch for anyone building their own web-agent evals. WebShop's dense, decomposable reward (`r_type × (attr + option + price) / n`) is the opposite bet: partial credit that makes RL trainable, at the cost of a scoring function complex enough to need its own unit tests.

**Test coverage is inversely correlated with eval sophistication.** WebArena is the only repo with real engineering hygiene (31 tests, `mypy --strict` in CI, pre-commit, beartype) — though its CI can't actually exercise the browser tests without a hosted instance. WebShop's 17 tests are narrow but well-aimed: they test the reward function and the scrapers, i.e. exactly the two places a silent bug would corrupt every reported number. WebLINX has 7 tests, one of which is an empty stub, and notably no tests over `weblinx/eval/metrics.py` — the code producing its leaderboard. Mind2Web has **no tests and no CI at all**, despite being the most-forked evaluation protocol of the four.

**Both live-environment repos now defer to a successor framework.** WebArena's README points to AgentLab/BrowserGym for new work, and WebLINX ships a `weblinx-browsergym` extension with a re-derived 1.1 dataset. If you're building on any of these today, BrowserGym is the convergent integration point — and it changes which steps get evaluated, so v1.0 and 1.1 numbers are not comparable.
