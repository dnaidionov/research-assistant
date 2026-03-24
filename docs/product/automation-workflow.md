# Automation Workflow

## Overview

The v1 workflow is a file-based orchestration pipeline executed by scripts and operated manually, semi-manually, or through a CLI-driven adapter runner.

The orchestration layer remains provider-agnostic. It prepares prompt packets, state files, work orders, and audit artifacts. It does not perform provider API calls in v1.

## Canonical Research Lifecycle

1. Intake
2. Research pass A
3. Research pass B
4. Critique of A by B
5. Critique of B by A
6. Judge
7. Claim extraction
8. Artifact writing

These stages must remain distinct. The workflow must not collapse research, critique, judge, and claim extraction into a single pass.

## `run_workflow.py` Scaffold Scope

`scripts/run_workflow.py` currently scaffolds the six execution-stage prompt packets:

1. Intake
2. Research A
3. Research B
4. Critique A on B
5. Critique B on A
6. Judge

Claim extraction and artifact writing remain separate downstream steps. That split is deliberate: the runner creates the auditable core research exchange first, while later transformations stay isolated in their own scripts.

## `execute_workflow.py` Automation Scope

`scripts/execute_workflow.py` automates the current 2-pass workflow through configurable CLI adapters.

The current default adapter assignment is:

1. intake in Codex
2. research A in Codex and research B in Gemini in parallel
3. critique A on B in Codex and critique B on A in Gemini in parallel
4. judge in Gemini
5. structured-output validation and stage claim sidecar generation for research A, research B, and judge
6. claim extraction
7. final artifact generation

The runner is file-driven. It waits on required stage output artifacts, updates `workflow-state.json`, and writes per-step logs into the run directory.
It assumes the external CLIs can complete a stage from a single prompt and write the requested output artifact without manual intervention.
It also emits live stage progress. In interactive terminals it redraws status in place; in captured output it emits ordered start and completion events.
Antigravity remains available as an adapter option but is no longer the default secondary adapter.

## Stage Intent

### 1. Intake
- normalize the brief
- identify missing information
- restate constraints without adding facts

### 2. Research pass A
- produce an independent research report
- separate facts and inference
- include inline citations
- use canonical external citation IDs for evidence, not ad hoc labels or stage references

### 3. Research pass B
- produce a second independent research report
- preserve independent reasoning from pass A
- follow the same canonical external citation scheme as pass A

### 4. Critique of A by B
- challenge unsupported claims in pass A
- preserve disagreements for adjudication

### 5. Critique of B by A
- challenge unsupported claims in pass B
- preserve disagreements for adjudication

### 6. Judge
- synthesize supported conclusions
- keep unresolved disagreements visible
- distinguish supported conclusions from open questions
- preserve external evidence citations from the research record instead of replacing them with stage references

### 7. Claim extraction
- convert markdown into a v1 claim register with stable `C001`-style IDs
- separate internal workflow provenance from external evidence sources where marker classification allows
- retain explicit markers such as citations and confidence where present
- treat the current output as a draft audit artifact, not as a fully reliable truth register

### 8. Artifact writing
- produce the final user-facing artifact
- use only cited claims from prior stages
- include summary, option comparison, recommendation, confidence or uncertainty, references, and open questions
- keep workflow provenance in audit artifacts, not in the user-facing references section

## Run Artifacts

Each run writes to `jobs/<job-name>/runs/<run-id>/`.

The run directory contains:

- `prompt-packets/`
- `stage-outputs/`
- `stage-claims/`
- `sources.json`
- `workflow-state.json`
- `WORK_ORDER.md`
- `audit/`
- `logs/`

The workflow script writes placeholder stage outputs as part of the scaffold so the run is auditable before any provider execution happens.

## Job-Level Artifacts

Each job repo also contains:

- `outputs/`
- `evidence/`
- `audit/`
- `logs/`

Promoted deliverables belong in those job-level directories, not in the assistant repo.

## Current Script Responsibilities

### `scripts/run_workflow.py`
- validates the job repo
- accepts a job name, a job id from `jobs-index` metadata, or an explicit job path
- creates a new run directory
- resolves job names and ids via `jobs-index/` or the jobs root
- renders prompt packets for the six execution stages
- writes explicit upstream stage-output artifact references into prompt packets and the work order
- scaffolds the run-level source registry at `sources.json`
- scaffolds structured JSON output targets for research A, research B, and judge
- writes `workflow-state.json`
- writes `WORK_ORDER.md`
- writes run audit files and placeholder output targets

### `scripts/execute_workflow.py`
- ensures the target run exists
- accepts a job name, a job id from `jobs-index` metadata, or an explicit job path
- resolves primary and secondary execution roles through named CLI adapters
- defaults to Codex as the primary adapter and Gemini as the secondary adapter
- keeps Antigravity available as an alternate adapter
- passes each tool explicit stage metadata including stage id, prompt-packet path, markdown output path, structured-output path where required, and source-registry path
- wraps stdout-oriented chat adapters by recovering markdown artifacts from stdout when they do not write the requested stage file directly
- synthesizes structured JSON from markdown only as a migration fallback when a structured stage does not write its JSON file directly
- reports stage start, completion, and failure status while the workflow runs
- executes the two research stages in parallel
- executes the two critique stages in parallel
- validates structured research and judge outputs against source-aware contracts before downstream execution continues
- merges stage-declared sources into the run-level `sources.json` registry and rejects unresolved source IDs
- treats `sources.json` as runner-owned state; stage agents may read it but should not modify it directly, and direct edits are discarded before merge
- extracts claim sidecars for `research-a`, `research-b`, and `judge`
- uses structured judge JSON for automated claim-register generation when available
- keeps section-aware markdown validation as a migration backstop for research and judge contracts
- keeps non-truth-critical narrative sections flexible in structured validation so usable research is not rejected over presentation-shape variance
- waits for judge completion before downstream processing
- runs claim extraction and final artifact generation automatically
- supports idempotent resume by skipping completed stage artifacts and downstream outputs
- updates workflow state and marks failed stages explicitly when an adapter exits non-zero or leaves placeholder output behind
- writes per-stage driver logs with command, return code, stdout, stderr, output-path status, and output preview for troubleshooting

### `scripts/extract_claims.py`
- parses markdown into atomic claims
- assigns stable `C001`-style IDs
- separates bracketed markers into provenance, external evidence, and unclassified buckets
- captures explicit confidence labels when present
- classifies disagreements and confidence summaries as evaluation-oriented claims instead of defaulting them to facts
- can fail on uncited facts and uncited inferences in strict mode when used as a hard validator
- flags provenance-only supported facts for downstream gating
- rejects workflow-stage references as evidence citations
- still relies on lexical and markdown-structure heuristics rather than semantic parsing

### `scripts/generate_final_artifact.py`
- reads the judge artifact and claim register
- rejects uncited facts, provenance-only facts, and unclassified markers
- writes a structured final artifact with external references only
- keeps workflow provenance out of the user-facing references section

### `scripts/validate_job.py`
- validates that a job repo has the required files and directories
- checks that the job is separate from the assistant repo
- checks that key config and artifact files are readable
- validates that `runs/` is a usable directory path
- checks that job-template requirements remain consistent with product docs
- can validate minimum readiness for final artifact generation
- returns structured validation results with explicit exit codes

## Constraints

- The assistant repo contains no research data.
- All run artifacts are written into the job repo.
- Final outputs may not contain uncited factual claims.
- Facts and inference must remain distinguishable where possible.
- Disagreements must be preserved until the judge stage.
- Workflow provenance and external evidence are different and must not be conflated.
- Stage references such as `research-a`, `judge`, or critique artifact IDs do not satisfy evidence-citation requirements.
- Research and judge stages must pass structured source-aware validation before the workflow may continue downstream.

## Planned Hardening

The intended next hardening steps are:

1. extend structured contracts to critique stages
2. collapse stage validation and publication gating into a shared validation module
3. remove markdown-to-JSON migration fallbacks once adapters write JSON deterministically
4. strengthen source-registry governance beyond simple ID resolution
5. replace marker-based provenance/evidence classification with stronger semantic handling only if the simpler approach proves insufficient
