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
- Uncertainty must be explicit, not implied.
- Disagreements must remain visible through critique and judge stages.
- Prompt packets must point to concrete run output paths for auditability.

## Output Contracts

The four canonical prompts now enforce explicit downstream contracts:

- `intake-template.md` returns JSON only, separating `known_facts`, `working_inferences`, and `uncertainty_notes`, and now requires `known_facts` to reference canonical intake-declared source IDs plus a short supporting `source_excerpt` and stable `source_anchor`.
- the runner now decomposes intake internally into source declaration, fact lineage, normalization, and merge substeps, but the final intake artifact still conforms to the same intake-template contract
- `research-template.md` returns fixed markdown sections with numbered fact and inference claims, explicit confidence labels, and a source-evaluation section.
- `critique-template.md` returns fixed markdown sections that explicitly attack unsupported claims, weak sources, omissions, and overreach.
- `judge-template.md` returns fixed markdown sections that separate supported conclusions from synthesis inferences, preserve unresolved disagreement when evidence is mixed, and may add a `# Brief Improvement Recommendations` section when the requester could materially improve the outcome by clarifying missing inputs.
- `artifact-writing-template.md` returns fixed markdown sections for executive summary, option comparison, recommendation, confidence or uncertainty, external references, and open questions, plus an optional `# Brief Improvement Recommendations` section rendered after confidence and before references when the judged synthesis contains actionable upstream improvements.
