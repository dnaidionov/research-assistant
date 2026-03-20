# Prompt System

## Location

Shared prompt templates live in `shared/prompts/`.

## Templates

- `intake-template.md`
- `research-template.md`
- `critique-template.md`
- `judge-template.md`
- `claim-extraction-template.md`
- `artifact-writing-template.md`

## Rendering Model

`scripts/run_workflow.py` renders stage-specific prompt packets into the target run directory.

The rendered packets are execution artifacts, not source templates.

For example:

- research pass A and research pass B both use `research-template.md`
- critique of A by B and critique of B by A both use `critique-template.md`

## Rules

- Every stage prompt must preserve provider-agnostic orchestration.
- Factual claims must remain cited.
- Facts and inference must be separated where possible.
- Disagreements must remain visible through critique and judge stages.
- Prompt packets must point to concrete run output paths for auditability.
