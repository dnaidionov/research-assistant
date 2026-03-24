# Codex Handoff

## Objective

Turn the repository into a usable orchestration framework for structured multi-stage research runs.

## Current Architecture

- `~/Projects/research-hub/research-assistant/` = framework repo
- `~/Projects/research-hub/jobs/<job-name>/` = one independent repo per research job

## Implemented v1 Scope

The current v1 now supports:

1. validating job repos
   including repo-boundary, readability, runs-path, and template-doc consistency checks
2. scaffolding workflow runs by job name or job path
3. rendering prompt packets for the six core execution stages
4. writing workflow state and work orders
5. generating placeholder stage outputs
6. scaffolding research and judge claim-sidecar targets inside each run
7. extracting atomic claims from markdown into a claim register with stable `C001`-style IDs and separated provenance/evidence markers
8. generating a downstream structured final artifact with external references only
9. automating the current adapter-driven execution split through a separate workflow runner
10. preserving audit artifacts inside the job repo

The current default automated split is:

1. `intake` in Codex
2. `research-a` in Codex and `research-b` in Gemini in parallel
3. `critique-a-on-b` in Codex and `critique-b-on-a` in Gemini in parallel
4. `judge` in Gemini
5. stage claim sidecar extraction and section-aware validation for `research-a`, `research-b`, and `judge`
6. claim extraction
7. final artifact generation

The runner is file-driven and resume-safe. It depends on the selected external CLIs being able to consume a single stage prompt. For stdout-oriented chat adapters such as Gemini and Antigravity, the runner can recover markdown stage artifacts from stdout when the adapter does not write the requested file directly. Antigravity remains supported as an alternate adapter.
Driver logs record the invoked command, return code, stdout, stderr, output-path status, and a preview of the generated artifact so placeholder or misdirected-output failures can be diagnosed after the fact.

## Canonical Research Lifecycle

1. intake
2. research pass A
3. research pass B
4. critique of A on B
5. critique of B on A
6. judge
7. claim extraction
8. artifact writing

`scripts/run_workflow.py` currently scaffolds stages 1 through 6. `scripts/execute_workflow.py` can now run those six stages with the current adapter-driven split and then trigger downstream claim extraction and artifact writing.

## Constraints

- Do not collapse assistant and jobs into one repo.
- Do not remove the dual research passes, dual critiques, or judge stage.
- Do not assume a single model or provider.
- Do not store real research data in the assistant repo.
- Prefer plain files over opaque storage.

## Expected Artifacts Per Run

Inside a job repo:

- `runs/<run-id>/prompt-packets/`
- `runs/<run-id>/stage-outputs/`
- `runs/<run-id>/stage-claims/`
- `runs/<run-id>/workflow-state.json`
- `runs/<run-id>/WORK_ORDER.md`
- `runs/<run-id>/audit/`
- `runs/<run-id>/logs/`

At the job root:

- `outputs/`
- `evidence/`
- `audit/`
- `logs/`

## Still Out Of Scope

- provider API integration
- automatic web retrieval
- automated citation verification
- UI
