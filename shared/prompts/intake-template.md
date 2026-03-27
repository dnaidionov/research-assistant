# Intake Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Job Directory: `{job_dir}`
Expected Output: `{stage_output_path}`

## Objective

Normalize the brief into an execution-ready intake record without adding external facts.

## Non-Negotiable Rules

- Do not invent evidence, sources, or conclusions.
- Keep missing information explicit.
- Convert ambiguous scope into concrete questions to resolve later.
- Preserve the distinction between provided facts and working assumptions.
- If the brief contains uncertainty or ambiguity, record it explicitly instead of resolving it by guesswork.
- Do not include factual claims that are not grounded in the provided materials.

## Output Contract

Return JSON only. No markdown fences. No prose before or after the JSON.

Use exactly these top-level keys:

- `question`
- `scope`
- `constraints`
- `assumptions`
- `missing_information`
- `required_artifacts`
- `notes_for_researchers`
- `known_facts`
- `working_inferences`
- `uncertainty_notes`
- `sources`

### Field Requirements

- `question`: string
- `scope`: array of strings
- `constraints`: array of strings
- `assumptions`: array of strings
- `missing_information`: array of strings
- `required_artifacts`: array of strings
- `notes_for_researchers`: array of strings
- `known_facts`: array of objects with `id`, `statement`, `source_ids`, `source_excerpt`, and `source_anchor`
- `working_inferences`: array of objects with `statement` and `why_it_is_inference`
- `uncertainty_notes`: array of strings
- `sources`: array of source objects with `id`, `title`, `type`, `authority`, `locator`, and optional `source_class`

### Classification Rules

- Put only information directly present in the brief or config into `known_facts`.
- Put interpretations, extrapolations, or provisional planning judgments into `working_inferences`.
- If an item could plausibly be challenged as not explicitly stated, treat it as inference, not fact.
- Every `known_facts` item must cite one or more source IDs from `sources`; do not use freeform `source_basis`.
- Define canonical `job_input` sources for the provided materials you actually used, typically `DOC-BRIEF` for `brief.md` and `DOC-CONFIG` for `config.yaml`.
- Keep `known_facts.statement` as a normalized statement of the source material, not a new conclusion.
- Every `known_facts` item must include a short `source_excerpt` copied or closely preserved from the provided material so the fact can be audited later.
- `source_excerpt` should be brief and specific. Do not fabricate wording that does not appear in the source.
- Every `known_facts` item must include a stable `source_anchor` that points back to where the excerpt came from, for example `brief.md#Question`, `brief.md#L12-L16`, or `config.yaml#requirements.require_citations`.
- Prefer stable structural anchors such as headings or key paths when possible; use line-style anchors only when no better stable anchor exists.

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
