# Judge Synthesis Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`
Expected Structured Output: `{stage_structured_output_path}`
Run Source Registry: `{source_registry_path}`

## Objective

Synthesize research pass A, research pass B, and both critiques into a judge report that keeps the reasoning auditable.

## Non-Negotiable Rules

- Separate supported conclusions from unresolved disagreements.
- Never erase disagreement just to make the output cleaner.
- Every factual claim must remain cited.
- Preserve the original external evidence IDs from the research record, such as `[SRC-001]` or `[DOC-001]`.
- Do not replace external citations with workflow-stage references such as `[02-research-a]` or `[05-critique-b-on-a]`.
- Label inferences and confidence explicitly.
- Keep a traceable path from synthesis back to the research passes and critiques.
- Where evidence is mixed, preserve the disagreement instead of pretending the stronger narrative won by default.
- If neither side is adequately supported, say so directly.

## Output Contract

Write two artifacts:

- Markdown at `{stage_output_path}`
- Structured JSON at `{stage_structured_output_path}`

Return markdown using exactly these top-level sections in this order:

1. `# Supported Conclusions`
2. `# Inferences And Synthesis Judgments`
3. `# Unresolved Disagreements`
4. `# Confidence Assessment`
5. `# Evidence Gaps`
6. `# Rationale And Traceability`
7. `# Recommended Final Artifact Structure`

### Section Rules

#### `# Supported Conclusions`

- Use numbered items.
- Include only conclusions that are adequately supported across the record.
- Every factual conclusion must include inline external citations.

#### `# Inferences And Synthesis Judgments`

- Use numbered items.
- Mark each item clearly as inference.
- Each item must cite the supporting external evidence and end with `Confidence: low|medium|high`.

#### `# Unresolved Disagreements`

- List disagreements that remain open because evidence is mixed, incomplete, ambiguous, or contested.
- Treat this section as adjudication, not as a place to invent new uncited facts.
- For each disagreement, state:
  - the disputed point
  - the strongest case on each side
  - why it remains unresolved

#### `# Confidence Assessment`

- Summarize confidence by topic, not just globally.
- Explain which confidence limits come from evidence quality, coverage, recency, or conflict.
- If you mention factual details here, keep the supporting external citations inline.

#### `# Evidence Gaps`

- Identify the additional evidence most likely to resolve the remaining disputes.

#### `# Rationale And Traceability`

- Briefly explain why some claims were accepted, rejected, or left unresolved.
- Reference the relevant research passes and critiques directly for provenance, but do not use those stage references as evidence citations.

#### `# Recommended Final Artifact Structure`

- Provide the recommended structure for the final artifact without adding new factual claims.

### Structured JSON Contract

Write JSON with these top-level keys:

- `stage`
- `supported_conclusions`
- `synthesis_judgments`
- `unresolved_disagreements`
- `confidence_assessment`
- `evidence_gaps`
- `rationale`
- `recommended_artifact_structure`
- `sources`

Rules:

- `stage` must equal `{stage_id}`.
- Every `supported_conclusions` item must contain `id`, `text`, and `evidence_sources`.
- Every `synthesis_judgments` item must contain `id`, `text`, `evidence_sources`, and `confidence`.
- When possible, add `support_links` to supported conclusions and synthesis judgments as a typed list of `{{ "source_id", "role" }}` objects.
- If a synthesis judgment depends on earlier local conclusion IDs, record those under `claim_dependencies` instead of placing them in `support_links.source_id`.
- Do not use local claim IDs such as `F-001`, `I-001`, or `C-001` inside `support_links.source_id`.
- `support_links.role` must be one of: `evidence`, `context`, `challenge`, `provenance`.
- Use `evidence` for external support that justifies the conclusion.
- Use `evidence` for `job_input` too when the brief or provided input directly states a current-system fact, requirement, or constraint that the conclusion is about.
- Use `context` for background inputs that materially shape interpretation but are not the main proof.
- Use `challenge` when a source keeps the judgment narrower or less certain than the strongest narrative suggests.
- Use `provenance` for workflow-stage traceability only. Provenance is not evidence.
- `confidence` must be `low`, `medium`, or `high`.
- `unresolved_disagreements` may be either:
  - a list of strings or `{{ "text": ... }}` entries, or
  - a list of structured disagreement objects with `point`, `case_a`, `case_b`, and `reason_unresolved`
- `confidence_assessment` may be either:
  - a string
  - a list of strings or `{{ "text": ... }}` entries
  - an object with `summary` and optional `topics`, where each topic contains `topic`, optional `confidence`, and `rationale`
- `recommended_artifact_structure` may be either:
  - a string
  - a list of strings or `{{ "text": ... }}` entries
  - an object with `sections`, where `sections` is a list of section titles
- Every cited external source id must be declared in `sources`.
- Every `sources` item must include `id`, `title`, `type`, `authority`, and `locator`, and should include `source_class` when known.
- Prefer explicit source classes:
  - `external_evidence`
  - `job_input`
  - `workflow_provenance`
  - `recovered_provisional`
- Workflow-stage references may appear in `rationale` for provenance, but never as evidence.
- Supported conclusions and synthesis judgments must still carry canonical external evidence in `evidence_sources`; `support_links` adds typed semantics and provenance, it does not replace evidence.
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
