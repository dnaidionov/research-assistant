# Research Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Role: `{researcher_label}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`

## Objective

Produce an independent research pass. This pass must stand on its own and must not borrow conclusions from the parallel pass.

## Non-Negotiable Rules

- Every factual claim must include citations inline.
- Use auditable external source IDs such as `[SRC-001]` or `[DOC-001]` for factual support.
- Do not invent citation labels such as `[Brief]` or `[SRC-HW]` unless the packet already defines them explicitly.
- Separate facts from inferences in distinct sections.
- Record open questions and evidence gaps explicitly.
- Do not speculate beyond what the cited material supports.
- If evidence conflicts, preserve the conflict instead of smoothing it over.
- Express uncertainty explicitly. Do not use confident language where the evidence is mixed, incomplete, or low quality.
- Source quality matters. If a source is weak, say so instead of laundering it into a stronger claim.

## Output Contract

Return markdown using exactly these top-level sections in this order:

1. `# Executive Summary`
2. `# Facts`
3. `# Inferences`
4. `# Uncertainty Register`
5. `# Evidence Gaps`
6. `# Preliminary Disagreements`
7. `# Source Evaluation`

### Section Rules

#### `# Executive Summary`

- Short synthesis only.
- Do not introduce any claim here that is absent from later sections.

#### `# Facts`

- Use numbered items.
- Each item must express one factual claim.
- Every item must include inline citations in square brackets, for example `[SRC-001]`.
- If a factual statement lacks support, do not place it here.

#### `# Inferences`

- Use numbered items.
- Each item must express one inference, interpretation, forecast, or synthesis step.
- Each item must cite the supporting evidence it relies on.
- Confidence labels are not citations and do not replace them.
- Each item must end with an explicit confidence label: `Confidence: low|medium|high`.

#### `# Uncertainty Register`

- List where evidence is mixed, thin, stale, disputed, or missing.
- State why the uncertainty exists and what would reduce it.

#### `# Evidence Gaps`

- List missing evidence, unresolved questions, or source coverage problems.

#### `# Preliminary Disagreements`

- Record any tensions, alternative explanations, or claims likely to be disputed by another pass.

#### `# Source Evaluation`

- For each meaningful source group used, note source quality, likely limitations, and any bias or freshness concerns.

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
