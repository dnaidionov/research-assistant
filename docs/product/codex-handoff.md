# Codex Handoff

## Objective

Turn the repository into a usable orchestration framework for structured multi-stage research runs.

## Current Architecture

- `~/Projects/research-hub/research-assistant/` = framework repo
- `~/Projects/research-hub/jobs/<job-name>/` = one independent repo per research job

## Implemented v1 Scope

The current v1 now supports:

1. validating job repos
2. scaffolding workflow runs
3. rendering prompt packets for each stage
4. writing workflow state and work orders
5. generating placeholder stage outputs
6. extracting atomic claims from markdown
7. preserving audit artifacts inside the job repo

## Canonical Workflow

1. intake
2. research pass A
3. research pass B
4. critique of A by B
5. critique of B by A
6. judge synthesis
7. claim extraction
8. artifact writing

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
