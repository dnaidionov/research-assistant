# System Invariants

These rules must not be violated by future changes.

## Repo boundaries
- The `research-assistant` repo contains framework logic, prompts, templates, schemas, scripts, and documentation only.
- The `research-assistant` repo must never contain real research data.
- Each research job lives in its own independent repo under `~/Projects/research-hub/jobs/`.
- The `jobs/` directory is only a container, not a git repo.

## Workflow
- The workflow is multi-stage, not single-pass.
- Every run must include intake, research, critique, and judge stages.
- Independent research passes must be generated before cross-review.
- Disagreements must be preserved until explicitly resolved.

## Evidence and quality
- No uncited factual claims are allowed in final outputs.
- Facts must be distinguishable from inference.
- Claims must be traceable to sources.
- Workflow provenance and external evidence must be modeled as different things.
- Source evaluation is required, not optional.
- Uncertainty must be explicit where evidence is weak or mixed.
- Non-claim artifacts such as structure notes and file references must not be promoted into truth validation unchanged.

## Implementation
- Scripts should write artifacts into the job repo, never into the assistant repo.
- The system should remain provider-agnostic at the orchestration layer.
- Structure and auditability matter more than convenience.
- Product docs must stay explicit about what is implemented now versus what is only a target design.
