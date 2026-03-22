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
6. extracting atomic claims from markdown into a claim register with stable `C001`-style IDs and separated provenance/evidence markers
7. generating a downstream structured final artifact with external references only
8. automating the current Codex/Antigravity execution split through a separate workflow runner
9. preserving audit artifacts inside the job repo

The current automated split is:

1. `intake` in Codex
2. `research-a` in Codex and `research-b` in Antigravity in parallel
3. `critique-a-on-b` in Codex and `critique-b-on-a` in Antigravity in parallel
4. `judge` in Antigravity
5. claim extraction
6. final artifact generation

The runner is file-driven and resume-safe. It depends on the external CLIs being able to consume a single stage prompt and write the requested artifact path non-interactively.

## Canonical Research Lifecycle

1. intake
2. research pass A
3. research pass B
4. critique of A on B
5. critique of B on A
6. judge
7. claim extraction
8. artifact writing

`scripts/run_workflow.py` currently scaffolds stages 1 through 6. `scripts/execute_workflow.py` can now run those six stages with the current Codex/Antigravity split and then trigger downstream claim extraction and artifact writing.

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
