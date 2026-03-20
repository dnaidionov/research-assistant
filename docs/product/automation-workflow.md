# Automation Workflow

## Overview

The v1 workflow is a file-based orchestration pipeline executed by scripts and operated manually or semi-manually in Codex.

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

## Stage Intent

### 1. Intake
- normalize the brief
- identify missing information
- restate constraints without adding facts

### 2. Research pass A
- produce an independent research report
- separate facts and inference
- include inline citations

### 3. Research pass B
- produce a second independent research report
- preserve independent reasoning from pass A

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

### 7. Claim extraction
- convert the synthesis into atomic claims with stable `C001`-style IDs
- retain citations, fact or inference typing, and explicit confidence where present

### 8. Artifact writing
- produce the final user-facing artifact
- use only cited claims from prior stages
- include disagreement and open-question sections

## Run Artifacts

Each run writes to `jobs/<job-name>/runs/<run-id>/`.

The run directory contains:

- `prompt-packets/`
- `stage-outputs/`
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
- accepts either a job name or an explicit job path
- creates a new run directory
- resolves job names via `jobs-index/` or the jobs root
- renders prompt packets for the six execution stages
- writes `workflow-state.json`
- writes `WORK_ORDER.md`
- writes run audit files and placeholder output targets

### `scripts/extract_claims.py`
- parses markdown into atomic claims
- assigns stable `C001`-style IDs
- extracts citations
- captures explicit confidence labels when present
- marks claims as `fact` or `inference`
- can fail on uncited facts in strict mode

### `scripts/validate_job.py`
- validates that a job repo has the required files and directories
- checks that the job is separate from the assistant repo
- checks that key config and artifact files are readable
- validates that `runs/` is a usable directory path
- checks that job-template requirements remain consistent with product docs
- returns structured validation results with explicit exit codes

## Constraints

- The assistant repo contains no research data.
- All run artifacts are written into the job repo.
- Final outputs may not contain uncited factual claims.
- Facts and inference must remain distinguishable where possible.
- Disagreements must be preserved until the judge stage.
