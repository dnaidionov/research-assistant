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
8. preserving audit artifacts inside the job repo

## Canonical Research Lifecycle

1. intake
2. research pass A
3. research pass B
4. critique of A on B
5. critique of B on A
6. judge
7. claim extraction
8. artifact writing

`scripts/run_workflow.py` currently scaffolds stages 1 through 6. Claim extraction and artifact writing are intentionally separate downstream steps.

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
