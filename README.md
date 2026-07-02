# Research Assistant Framework

Research Assistant is a framework for running structured, auditable research workflows across multiple LLMs without mixing framework code and research data.

The assistant repository contains the orchestration system: prompts, schemas, scripts, templates, dashboard, and documentation. Actual research work lives in separate job repositories, one repo per research case. This separation is deliberate. It keeps the framework reusable, keeps research artifacts isolated, and makes each job independently versioned and shareable.

## Purpose

The product exists to make multi-stage research work more reliable than ordinary single-prompt LLM usage.

Instead of asking one model for one final answer, the framework breaks research into explicit stages such as intake, independent research passes, adversarial critique, judgment, claim extraction, and final artifact generation. The last of these stages produces two complementary deliverables: a deterministic final artifact and an LLM-synthesized final report, both claim-gated and both published into the job's `outputs/` directory. Each stage produces auditable files. Disagreement is preserved rather than erased, factual claims are expected to carry citations, and the system records which providers and models were actually used for a specific run.

## Why Use It

Use this framework when you need research outputs that are:

- more traceable than chat transcripts
- more reproducible than ad hoc prompting
- safer than a single-model answer
- organized as durable job artifacts rather than scattered notes

It is especially useful when the output matters enough that you want to inspect:

- what sources were used
- where models disagreed
- how a recommendation was formed
- which provider or model produced which stage
- what changed from run to run

## Best-Fit Research Types

This model is best suited to research tasks where comparison, evidence quality, and explicit tradeoffs matter more than raw speed.

Examples:

- vendor or tool selection
- product, platform, or architecture tradeoff analysis
- policy or regulatory impact analysis
- hardware, infrastructure, or procurement comparisons
- strategic option evaluation with competing recommendations
- decision memos where confidence, uncertainty, and disagreement should remain visible

The framework is intentionally adaptable across research domains. Fixture families let qualification, drift checks, and benchmark workflows exercise different research shapes without hardcoding the system to a single domain. Later, the docs should also include at least one concrete example job so the system is demonstrated on a real end-to-end case rather than only described abstractly.

## Core Operating Model

The system has two strict boundaries:

- Assistant repo: framework only
  Contains prompts, scripts, schemas, templates, dashboard code, and product and architecture docs.
- Job repos: research only
  Contain briefs, run artifacts, evidence, outputs, logs, and audit trails for a single research case.

This boundary is not cosmetic. It is one of the core architecture rules of the product.

## Typical Workflow

1. Create a job repo for a specific research case.
2. Write the brief and configuration in that job repo.
3. Scaffold a run directory for that job.
4. Execute stages either manually, through supported CLI adapters, or through the dashboard.
5. Preserve stage outputs, claims, evidence, and audit records inside the job repo.
6. Generate a final report from the judged synthesis and validated claims.

There are two main control surfaces:

- CLI: for direct scripting, controlled manual operation, and automation
- Dashboard UI: for inspecting jobs, creating jobs, launching runs, and reviewing execution artifacts interactively

The dashboard is browser-based but runs locally on the user’s machine. It is not a hosted service. It works against local job repositories and the local assistant repo.

## Quick Setup

This is the shortest path to a usable local setup.

1. Clone the assistant repo into the default assistant path or update the path config later:

```bash
git clone <your-fork-or-origin> ~/Projects/research-hub/research-assistant
cd ~/Projects/research-hub/research-assistant
```

2. Review `config/paths.yaml`.

By default it uses:

- `assistant_root: ~/Projects/research-hub/research-assistant`
- `jobs_root: ~/Projects/research-hub/jobs`

If your install layout is different, edit that file before using the scripts.
The shipped `assistant_root` is a documented default; local scripts still use the repo’s actual runtime location and only enforce mismatches when you set a custom assistant path.

3. Authenticate the tools you actually plan to use.

- GitHub auth is needed for repo creation, sync, PR workflows, and some dashboard-backed git operations.
- LLM provider auth is needed for provider qualification, manual stage launching, and automated execution.

4. Create a job repo.

```bash
./scripts/create_job.sh my-project-1
```

5. Fill in:

- `~/Projects/research-hub/jobs/my-project-1/brief.md`
- `~/Projects/research-hub/jobs/my-project-1/config.yaml`

6. Validate the job:

```bash
python3 scripts/validate_job.py --job-dir ~/Projects/research-hub/jobs/my-project-1
```

7. Scaffold a run:

```bash
python3 scripts/run_workflow.py --job-path ~/Projects/research-hub/jobs/my-project-1 --run-id run-001
```

8. Choose execution mode:

- Manual: run stages yourself from `prompt-packets/`, then record the attempted provider/model with `scripts/record_manual_stage.py`
- Single-stage launcher: use `scripts/run_stage.py` for one stage at a time, with optional per-step provider/model override
- Automated runner: use `scripts/execute_workflow.py` for the full configured workflow

9. When judge output is ready, downstream scripts can extract claims and generate the final artifact and final report automatically.

## Manual Stage Execution

The scaffold covers these six execution stages:

1. `intake`
2. `research-a`
3. `research-b`
4. `critique-a-on-b`
5. `critique-b-on-a`
6. `judge`

Manual execution still writes into the run directory:

- prompt packets live under `runs/<run-id>/prompt-packets/`
- final stage outputs live under `runs/<run-id>/stage-outputs/`
- structured stage JSON lives under `runs/<run-id>/stage-outputs/*.json`

When a stage depends on an earlier stage, use the prior stage output artifact from `stage-outputs/`, not the prior prompt packet.

After a manual stage attempt, record what was actually used:

```bash
python3 scripts/record_manual_stage.py \
  --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001 \
  --stage research-b \
  --status completed \
  --provider-key claude_research \
  --adapter claude \
  --model claude-sonnet-4-6
```

`started`, `completed`, `failed`, and `cancelled` all preserve the attempted provider/model. `completed` requires the expected stage artifact to exist. `failed` and `cancelled` do not.

## Single-Stage Launching

If you want the framework to execute one stage for you without running the whole workflow, use:

```bash
python3 scripts/run_stage.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --stage research-b
```

By default, the stage uses the provider/model resolved from the job config. You can override that for the launched step only:

```bash
python3 scripts/run_stage.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --stage research-b \
  --adapter claude \
  --model claude-sonnet-4-6 \
  --provider-key manual_claude_override
```

Override precedence for a launched step is:

1. explicit step override flags
2. stage provider/model from `config.yaml`
3. fallback CLI split only when no job execution config exists

The underlying job config is not mutated. The run audit records both the configured assignment and the actual attempted assignment if they differ.

## Automated Workflow Execution

Run the current 2-pass workflow end to end with:

```bash
python3 scripts/execute_workflow.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001
```

The fallback default split is:

1. `intake` in Codex
2. `research-a` in Codex and `research-b` in Gemini in parallel
3. `critique-a-on-b` in Codex and `critique-b-on-a` in Gemini in parallel
4. `judge` in Gemini
5. claim extraction
6. deterministic final artifact generation
7. LLM-driven final report synthesis — the last step of every run, reusing the judge stage's provider/model unless `workflow.execution.stage_providers.final-report` routes it elsewhere

That split is only the fallback. Prefer job-level execution config in `config.yaml` for durable stage routing and model pinning.

Automated runs persist:

- workflow state in `runs/<run-id>/workflow-state.json`, including independently resumable status for claim extraction, the deterministic final artifact, and final report synthesis under `post_processing`
- usage telemetry in `runs/<run-id>/audit/usage/`
- configured and actual execution records in `runs/<run-id>/audit/execution-config.json`
- the exact `brief.md` and `config.yaml` the run was scaffolded against in `runs/<run-id>/job-inputs/`
- both final deliverables in the job's `outputs/` directory: `outputs/final-<run-id>.md` (deterministic) and `outputs/final-report-<run-id>.md` (LLM-synthesized, published after it passes claim/reference validation)

Because the prompt packets embed the brief at scaffold time, execution refuses to continue a run whose `brief.md` has changed since scaffolding; start a new run for an updated brief. Config drift is journaled as a warning, and execution-relevant config changes are still rejected by the execution-config snapshot guard.

## Claim Extraction, Final Artifact, and Final Report

Extract claims from a markdown report with:

```bash
python3 scripts/extract_claims.py \
  --input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --output ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json \
  --strict
```

Generate the final artifact with:

```bash
python3 scripts/generate_final_artifact.py \
  --judge-input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.md \
  --judge-structured-input ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/06-judge.json \
  --claim-register ~/Projects/research-hub/jobs/my-project-1/evidence/claims-run-001.json \
  --output ~/Projects/research-hub/jobs/my-project-1/outputs/final-run-001.md \
  --config ~/Projects/research-hub/jobs/my-project-1/config.yaml
```

The final artifact remains operator-reviewed output, not autonomous truth certification.

`execute_workflow.py` runs a second, LLM-driven synthesis step after the deterministic artifact — the last step of the workflow. It can also be invoked directly:

```bash
python3 scripts/generate_final_report.py \
  --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001 \
  --job-dir ~/Projects/research-hub/jobs/my-project-1 \
  --adapter-name claude --adapter-bin claude \
  --output ~/Projects/research-hub/jobs/my-project-1/runs/run-001/stage-outputs/07-final-report.md
```

It synthesizes from the judge record and the claim register, following the judge's recommended report structure, and validates the result against the same claim/reference rules as the deterministic artifact: uncited facts or inferences, unresolved or blocked source IDs, and provenance-only citations all fail it closed, with the rejected draft kept at `07-final-report.md.rejected.md` for review. When run through `execute_workflow.py`, a validated report is also published to `outputs/final-report-<run-id>.md` in the job directory.

After a run, you can audit that external-evidence locators actually resolve (catching fabricated citations that pass schema validation), and optionally verify that the quoted evidence excerpts recorded by the research stages actually appear in the cited documents (catching paraphrased or invented quotes):

```bash
python3 scripts/check_source_links.py \
  --sources ~/Projects/research-hub/jobs/my-project-1/runs/run-001/sources.json \
  --verify-excerpts
```

For deeper (paid) verification, sampled LLM entailment spot-checks ask an adapter whether each quoted excerpt actually supports the claim citing it:

```bash
python3 scripts/verify_claim_entailment.py \
  --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001 \
  --job-dir ~/Projects/research-hub/jobs/my-project-1 \
  --adapter-name claude --adapter-bin claude --sample 5
```

## Local Dashboard

Start the dashboard with:

```bash
cd ~/Projects/research-hub/research-assistant/dashboards/ui
npm install
npm run dev
```

Then visit `http://localhost:3000`.

The dashboard can:

- inspect jobs and runs
- create jobs from the template
- edit `brief.md` and `config.yaml`
- launch scaffold or automated runs
- inspect run artifacts and execution config snapshots

## Authentication and Costs

Two practical points should be explicit:

- GitHub auth is required for features that create repos, sync branches, open PRs, or depend on git-backed UI workflows.
- Provider auth is required for qualification and any real stage execution through Codex, Claude, Gemini, or other adapters.

Running the workflow can incur real provider costs. Multi-pass research, critique, and judge stages are intentionally more expensive than one-shot prompting because they buy you auditability and adversarial structure.

## Detailed Setup and Configuration

For installation, configuration, authentication, path layout, and secrets guidance, use:

- [Installation and Configuration](docs/product/installation-and-configuration.md)
- [Automation Workflow](docs/product/automation-workflow.md)
- [Operator Playbook](docs/product/operator-playbook.md)
- [Product Spec](docs/product/product-spec.md)
- [UI Product Spec](docs/product/ui-spec.md)

## Structure

- `templates/` — job templates
- `shared/` — reusable prompts, policies, rubrics
- `schemas/` — validation schemas
- `scripts/` — orchestration and validation utilities
- `jobs-index/` — registry of research jobs, fixed inside the assistant repo
- `docs/` — product, architecture, and decision records
- `dashboards/ui/` — local browser UI for managing jobs and runs
- `inbox/` — project ideas and incoming notes

## Hard Constraint

This repo must never contain:

- real research data
- client or project source material
- sensitive source content
- job-specific outputs
