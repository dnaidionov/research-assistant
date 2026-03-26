# Critique Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Critic Role: `{critic_label}`
Target Role: `{target_label}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`
Expected Structured Output: `{stage_structured_output_path}`
Run Source Registry: `{source_registry_path}`

## Objective

Critique the target research pass adversarially. The goal is to find unsupported claims, weak evidence, missing alternatives, and places where inference is presented too confidently.

## Non-Negotiable Rules

- Do not rewrite the target report into agreement.
- Preserve disagreements and unresolved conflicts.
- Quote the exact claim IDs or passages being challenged where possible.
- Distinguish between invalid claims, weakly supported claims, and reasonable but incomplete claims.
- Attack omissions, overreach, and source weakness directly.
- If a claim is factually stated without citation support, call that out explicitly as a defect.
- If a conclusion outruns the cited evidence, classify it as overreach rather than a simple disagreement.

## Output Contract

Write two artifacts:

- Markdown at `{stage_output_path}`
- Structured JSON at `{stage_structured_output_path}`

Return markdown using exactly these top-level sections in this order:

1. `# Claims That Survive Review`
2. `# Unsupported Claims`
3. `# Weak Sources Or Citation Problems`
4. `# Omissions And Missing Alternatives`
5. `# Overreach And Overconfident Inference`
6. `# Unresolved Disagreements For Judge`
7. `# Overall Critique Summary`

### Section Rules

#### `# Claims That Survive Review`

- List only claims that remain materially defensible after review.
- Keep this section short. The critique is not a rewrite of the original report.

#### `# Unsupported Claims`

- For each item, include:
  - the quoted or referenced target claim
  - why support is missing or inadequate
  - what evidence would be needed to support it

#### `# Weak Sources Or Citation Problems`

- Identify weak, stale, indirect, low-credibility, or mismatched citations.
- Distinguish between source-quality issues and claim-quality issues.

#### `# Omissions And Missing Alternatives`

- Identify missing counterarguments, omitted explanations, or neglected evidence that could materially change the conclusion.

#### `# Overreach And Overconfident Inference`

- Identify where the report presents inference as fact, certainty as probability, or narrow evidence as broad conclusion.
- State the narrower claim that would still be justified, if any.

#### `# Unresolved Disagreements For Judge`

- Preserve disagreements that cannot be resolved from the available evidence.
- Do not force convergence.

#### `# Overall Critique Summary`

- Summarize the major failure modes of the target report.
- State the overall reliability judgment with an explicit confidence label: `Confidence: low|medium|high`.

### Structured JSON Contract

Write JSON with these top-level keys:

- `stage`
- `supported_claims`
- `unsupported_claims`
- `weak_source_issues`
- `omissions`
- `overreach`
- `unresolved_disagreements`
- `summary`
- `sources`

Rules:

- `stage` must equal `{stage_id}`.
- `supported_claims`, `unsupported_claims`, `weak_source_issues`, `omissions`, `overreach`, and `unresolved_disagreements` must be structured lists.
- `unsupported_claims` should preserve the challenged claim, why support is inadequate, and what evidence would be needed where possible.
- `summary` may be a string, a list, or an object with `text` and optional `confidence`.
- Every cited external source id must be declared in `sources`.
- Every `sources` item must include `id`, `title`, `type`, `authority`, and `locator`.
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
