# Research Assistant Framework

This repository contains the orchestration framework for structured, multi-LLM research workflows.

## Architecture

The system is split into two layers:
- Assistant = orchestration layer
- Jobs = independent research cases

Jobs are linked via metadata, not embedded

### 1. Assistant (this repo)
- prompts
- schemas
- scripts
- templates
- documentation

Contains **no research data**

### 2. Jobs (separate repos)
Located at:

~/Projects/research-hub/jobs/

Each job:
- is its own Git repository
- contains full research lifecycle artifacts
- can be shared independently

---

## Key Principles

- jobs are fully isolated (one repo per job)
- strict separation between system and data
- this repo contains no research data
- no uncited factual claims
- claim-level traceability
- adversarial validation
- reproducibility over convenience

---

## Structure

- `templates/` — job templates
- `shared/` — reusable prompts, policies, rubrics
- `schemas/` — validation schemas
- `scripts/` — automation utilities
- `jobs-index/` — registry of research jobs (metadata only)
- `docs/` — ideation, product design, decisions
- `dashboards/` — Obsidian-friendly navigation
- `inbox/` - inbox for new ideas

---

## Usage

1. Create a new job from template `scripts/create_job.sh`
2. Register it in `jobs-index/`
3. Run research workflow
4. Store all outputs inside the job repo

## Operator Quickstart

This is the shortest direct path to using the framework as it exists today.

### 1. Create a job repo

Create a new job under `~/Projects/research-hub/jobs/` and initialize it as its own git repo.

```bash
cd ~/Projects/research-hub/research-assistant
./scripts/create_job.sh my-project-1
```

Then fill in:

- `~/Projects/research-hub/jobs/my-project-1/brief.md`
- `~/Projects/research-hub/jobs/my-project-1/config.yaml`

If you want name-based lookup via `run_workflow.py`, also register the job in `jobs-index/`.

### 2. Validate the job structure

Run:

```bash
cd ~/Projects/research-hub/research-assistant
python3 scripts/validate_job.py --job-dir ~/Projects/research-hub/jobs/my-project-1
```

JSON output is available if you want machine-readable checks:

```bash
python3 scripts/validate_job.py --job-dir ~/Projects/research-hub/jobs/my-project-1 --json
```

### 3. Scaffold a workflow run

You can target a job by explicit path:

```bash
python3 scripts/run_workflow.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001
```

Or by job name if it exists in `jobs-index/`:

```bash
python3 scripts/run_workflow.py \
  --job-name my-project-1 \
  --run-id run-001
```

This creates:

- `runs/run-001/prompt-packets/`
- `runs/run-001/stage-outputs/`
- `runs/run-001/workflow-state.json`
- `runs/run-001/WORK_ORDER.md`
- `runs/run-001/audit/`
- `runs/run-001/logs/`

### 4. Execute the six scaffolded stages

Open the rendered prompt packets under:

`~/Projects/research-hub/jobs/my-project-1/runs/run-001/prompt-packets/`

The scaffold currently covers these stages:

1. intake
2. research-a
3. research-b
4. critique-a-on-b
5. critique-b-on-a
6. judge

Put the actual outputs into:

`~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/`

Important:

- the framework does not call provider APIs yet
- execution is still manual or handled by an external adapter
- all factual claims must remain cited
- facts and inference must stay separated where possible
- unresolved disagreement must remain visible through the judge stage

### Example execution mapping

This is an example, not a hard requirement. The framework stays provider-agnostic.

- `intake`: `ChatGPT` or `Codex`
- `research-a`: `ChatGPT`
- `research-b`: `Gemini`
- `critique-a-on-b`: same model family used for `research-a`
- `critique-b-on-a`: same model family used for `research-b`
- `judge`: the strongest reasoning model you trust most

Why this example is reasonable:

- using different models for `research-a` and `research-b` increases useful disagreement
- keeping each critique with its original research perspective preserves adversarial pressure
- using the strongest model for `judge` improves synthesis quality when evidence is mixed

Recommended operator pattern:

- use `Codex` to scaffold runs, manage files, and keep the repo state clean
- use model UIs or APIs such as `ChatGPT` and `Gemini` to execute the prompt packets
- write each stage result back into the matching file under `stage-outputs/`

### 5. Extract a claim register from a markdown report

For any markdown report, generate a JSON claim register like this:

```bash
python3 scripts/extract_claims.py \
  --input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --output ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json
```

Strict mode fails if extracted fact claims have no citations:

```bash
python3 scripts/extract_claims.py \
  --input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --output ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json \
  --strict
```

### 6. What is still manual

- provider/model execution
- source retrieval
- citation verification against source content
- promotion of accepted outputs into final job-level deliverables
- final artifact writing as an automated pipeline step

### 7. What the framework gives you now

- independent job repos
- auditable run scaffolding
- strict prompt packets
- workflow state and work order files
- placeholder output targets
- claim extraction from markdown
- structure validation

---

## Workflow

1. Intake → structured brief
2. Research A/B → independent parallel outputs
3. Critique A on B and B on A → adversarial cross-examination
4. Judge → resolution and synthesis
5. Claim extraction and artifact writing → downstream structured outputs

---

## Execution Model

- ChatGPT → design & reasoning
- Codex → implementation & execution
- Scripts → orchestration layer
- Jobs → persistent storage

---

## Important

This repo must never contain:
- real research data
- client/project names
- sensitive sources
