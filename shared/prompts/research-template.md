# Research Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Role: `{researcher_label}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`
Expected Structured Output: `{stage_structured_output_path}`
Run Source Registry: `{source_registry_path}`

## Objective

Produce an independent research pass. This pass must stand on its own and must not borrow conclusions from the parallel pass.

## Non-Negotiable Rules

- Every factual claim must include citations inline.
- Evidence is never obvious. Nearby or earlier citations do not count for a new item.
- Use auditable external source IDs such as `[SRC-001]` or `[DOC-001]` for factual support.
- Do not invent citation labels such as `[Brief]` or `[SRC-HW]` unless the packet already defines them explicitly.
- Separate facts from inferences in distinct sections.
- Record open questions and evidence gaps explicitly.
- Do not speculate beyond what the cited material supports.
- If evidence conflicts, preserve the conflict instead of smoothing it over.
- Express uncertainty explicitly. Do not use confident language where the evidence is mixed, incomplete, or low quality.
- Source quality matters. If a source is weak, say so instead of laundering it into a stronger claim.

## Output Contract

Write two artifacts:

- Markdown at `{stage_output_path}`
- Structured JSON at `{stage_structured_output_path}`

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
- The supporting evidence must be explicit on that exact item, even if similar evidence was already cited nearby.
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

### Structured JSON Contract

Write JSON with these top-level keys:

- `stage`
- `summary`
- `facts`
- `inferences`
- `uncertainties`
- `evidence_gaps`
- `preliminary_disagreements`
- `source_evaluation`
- `sources`

Rules:

- `stage` must equal `{stage_id}`.
- Every `facts` item must contain `id`, `text`, and `evidence_sources`.
- Every `inferences` item must contain `id`, `text`, `evidence_sources`, and `confidence`.
- Every fact and every world-claim inference must carry explicit evidence on that exact item. Nearby or previous citations do not satisfy the requirement.
- When possible, add `support_links` to each fact and inference item as a typed list of `{{ "source_id", "role" }}` objects.
- If an inference depends on earlier fact IDs such as `F-001`, record those under `claim_dependencies` instead of putting them inside `support_links.source_id`.
- Do not use local claim IDs such as `F-001`, `I-001`, or `C-001` inside `support_links.source_id`.
- `support_links.role` must be one of: `evidence`, `context`, `challenge`, `provenance`.
- Use `evidence` for external support that directly justifies the claim.
- Use `evidence` for `job_input` too when the brief or provided input directly states a current-system fact, requirement, or constraint that the claim is about.
- Use `context` for background inputs that inform scope or constraints but are not the main proof.
- Use `challenge` only when a cited source materially pushes against the claim.
- Use `provenance` for workflow artifacts or traceability records. Provenance is not evidence.
- `confidence` must be `low`, `medium`, or `high`.
- Every cited source id must be declared in `sources`.
- Every `sources` item must include `id`, `title`, `type`, `authority`, and `locator`, and should include `source_class` when known.
- Prefer explicit source classes:
  - `external_evidence`
  - `job_input`
  - `workflow_provenance`
  - `recovered_provisional`
- Preserve canonical external source IDs. Do not use workflow-stage references as evidence.
- Facts and inferences must still carry canonical external evidence in `evidence_sources`; `support_links` adds semantics and provenance, it does not replace evidence.
- `claim_dependencies` is for local reasoning traceability only; it does not replace external evidence citations.
- Use resolvable locators for sources. Prefer full URLs, concrete file paths, `file://` locators for attached files, or other stable followable URIs. Avoid vague locators such as `Various industry benchmarks`.
- Retain the exact locator you actually used. Do not collapse a specific page URL, file path, or attachment URI to a bare domain or site root unless no more precise locator is available.
- If only a degraded locator is known, keep it only as a last resort and state that precise source location was not retained.
- Treat `{source_registry_path}` as read-only reference material. Do not modify it directly; declare sources in this stage JSON and let the runner merge them.

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
