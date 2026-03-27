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

For the current design assessment and forward plan, see:

- [Product Spec](/Users/Dmitry_Naidionov/Projects/research-hub/research-assistant/docs/product/product-spec.md)
- [Redesign Proposal](/Users/Dmitry_Naidionov/Projects/research-hub/research-assistant/docs/product/redesign-proposal.md)

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

Or by job id if it is registered in `jobs-index/active/*.yaml`:

```bash
python3 scripts/run_workflow.py \
  --job-id my-project-1 \
  --run-id run-001
```

This creates:

- `runs/run-001/prompt-packets/`
- `runs/run-001/stage-outputs/`
- `runs/run-001/stage-claims/`
- `runs/run-001/sources.json`
- `runs/run-001/workflow-state.json`
- `runs/run-001/WORK_ORDER.md`
- `runs/run-001/audit/`
- `runs/run-001/logs/`

### 4. Execute the six scaffolded stages

This section describes the manual path. If you use the automated CLI-adapter runner, skip ahead to step 7.

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

The current structured-contract rollout also expects authoritative JSON artifacts for:

- `research-a` at `stage-outputs/02-research-a.json`
- `research-b` at `stage-outputs/03-research-b.json`
- `critique-a-on-b` at `stage-outputs/04-critique-a-on-b.json`
- `critique-b-on-a` at `stage-outputs/05-critique-b-on-a.json`
- `judge` at `stage-outputs/06-judge.json`

The run-level source registry lives at:

`~/Projects/research-hub/jobs/my-project-1/runs/run-001/sources.json`

That registry now normalizes source records into explicit source classes such as `external_evidence`, `job_input`, and `recovered_provisional`.

Structured research, critique, and judge JSON may also carry typed `support_links` on claim-like items. These links distinguish semantic roles such as `evidence`, `context`, `challenge`, and `provenance` instead of relying only on flat citation lists. When a later claim depends on an earlier local claim or fact, that dependency should be recorded separately in `claim_dependencies` rather than mixed into source support. `job_input` sources remain admissible evidence when they directly state current-system facts, requirements, or constraints under analysis.

Validated claim sidecars for `research-a`, `research-b`, both critiques, and `judge` are written into:

`~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-claims/`

When a stage depends on an earlier stage, use the prior stage output artifact from `stage-outputs/`, not the prior prompt packet from `prompt-packets/`.

Example:

- `research-a` and `research-b` should consume `stage-outputs/01-intake.json`
- critiques should consume the relevant research outputs from `stage-outputs/`
- `judge` should consume the critique outputs from `stage-outputs/`
- `research-a`, `research-b`, both critiques, and `judge` must produce valid structured JSON and pass source-aware citation validation before downstream workflow stages continue
- structured stages are no longer allowed to backfill authoritative JSON from markdown; they must write JSON directly or emit recoverable structured JSON in stdout

The rendered prompt packets and `WORK_ORDER.md` now state these upstream artifact paths explicitly.

Important:

- the framework does not call provider APIs yet
- stage execution can be manual or handled by an external adapter or CLI-based orchestrator
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

Strict mode fails if extracted fact or inference claims have no external evidence sources:

```bash
python3 scripts/extract_claims.py \
  --input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --output ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json \
  --strict
```

The claim register now separates:

- `provenance` = internal workflow artifacts that asserted or preserved a claim
- `evidence_sources` = external sources that support a claim about the world
- `unclassified_markers` = markers that could not be safely classified

For final outputs, provenance is useful for audit, but it is not enough evidence on its own.

### 6. Generate the final artifact

Once the judge artifact and claim register are ready, generate the final user-facing artifact like this:

```bash
python3 scripts/generate_final_artifact.py \
  --judge-input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --claim-register ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json \
  --output ~/Projects/research-hub/jobs/my-project-1/outputs/final-run-001.md
```

This script will fail if the claim register still contains:

- uncited facts
- uncited inferences where strict validation applies
- provenance-only supported facts
- unclassified markers

The final artifact includes:

- executive summary
- options comparison
- recommendation
- confidence and uncertainty
- references
- open questions

Important:

- the references section is for external sources only
- internal workflow provenance stays in audit artifacts, not in the user-facing references list

### 7. Automate the CLI split

The runner is adapter-based. Today the default configuration is:

- `intake` in Codex
- `research-a` in Codex
- `research-b` in Gemini
- `critique-a-on-b` in Codex
- `critique-b-on-a` in Gemini
- `judge` in Gemini

Then the runner will also perform:

- `extract_claims.py --strict`
- `validate_job.py --final-artifact-ready`
- `generate_final_artifact.py`

Use:

```bash
python3 scripts/execute_workflow.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001
```

If the job is registered in `jobs-index/`, you can use either of these instead:

```bash
python3 scripts/execute_workflow.py \
  --job-name my-project-1 \
  --run-id run-001
```

```bash
python3 scripts/execute_workflow.py \
  --job-id my-project-1 \
  --run-id run-001
```

This runner will:

- scaffold the run if it does not already exist
- execute the six workflow stages in the required order
- run `research-a` and `research-b` in parallel
- run `critique-a-on-b` and `critique-b-on-a` in parallel
- wait for both critiques before running `judge`
- extract claims from the structured judge artifact when available
- validate final-artifact readiness before generation
- generate the final artifact after readiness checks pass
- resume safely if a prior run already completed some stages
- report stage progress while it runs

In an interactive terminal, the runner redraws the current status in place. In non-interactive output capture, it emits ordered event lines such as:

- `codex: intake started`
- `codex: intake completed`
- `codex: research-a started`
- `gemini: research-b started`
- `system: claim-extraction completed`

It writes stage execution logs into:

- `runs/<run-id>/logs/`

It also updates:

- `runs/<run-id>/workflow-state.json`

Current adapter assumptions:

- Codex is invoked via the `codex` CLI
- Gemini is invoked via `gemini -p <prompt> -y`
- Antigravity remains available as an optional adapter via `antigravity chat --mode agent --yes`
- adapters must be able to read an instruction prompt and write the requested stage artifact without interactive editing

You can override the binaries or the selected adapters if needed:

```bash
python3 scripts/execute_workflow.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --codex-bin /path/to/codex \
  --gemini-bin /path/to/gemini \
  --antigravity-bin /path/to/antigravity
```

To switch the secondary execution role back to Antigravity:

```bash
python3 scripts/execute_workflow.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --secondary-adapter antigravity
```

The automated runner uses this fixed stage order:

1. `intake` in Codex
2. `research-a` in the primary adapter and `research-b` in the secondary adapter in parallel
3. `critique-a-on-b` in the primary adapter and `critique-b-on-a` in the secondary adapter in parallel
4. `judge` in the secondary adapter
5. `extract_claims.py --strict`
6. `validate_job.py --final-artifact-ready`
7. `generate_final_artifact.py`

This is intentionally file-driven rather than provider-integrated. The runner passes each adapter the stage id, prompt-packet path, markdown output path, structured-output path where required, and the run-level source registry path. It waits for the expected artifact to exist and no longer contain placeholder content. For structured stages, it validates the JSON contract and cited source IDs before downstream execution continues. Markdown-to-JSON synthesis remains only as a migration fallback when a structured stage fails to write its JSON file directly.

### 8. What is still manual

If you use the current automated runner for the supported Codex/Gemini default split, these are still manual:

- source retrieval
- citation verification against source content
- promotion of accepted outputs into final job-level deliverables
- configuring or replacing external execution adapters if your local CLI setup differs from the current adapter assumptions

### 9. What the framework gives you now

- independent job repos
- auditable run scaffolding
- automated adapter-driven execution for the current 2-pass workflow shape
- strict prompt packets
- workflow state and work order files
- placeholder output targets
- claim extraction from markdown
- final artifact generation from judge output plus claim register
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
