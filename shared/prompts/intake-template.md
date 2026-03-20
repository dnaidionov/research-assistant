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

### Field Requirements

- `question`: string
- `scope`: array of strings
- `constraints`: array of strings
- `assumptions`: array of strings
- `missing_information`: array of strings
- `required_artifacts`: array of strings
- `notes_for_researchers`: array of strings
- `known_facts`: array of objects with `statement` and `source_basis`
- `working_inferences`: array of objects with `statement` and `why_it_is_inference`
- `uncertainty_notes`: array of strings

### Classification Rules

- Put only information directly present in the brief or config into `known_facts`.
- Put interpretations, extrapolations, or provisional planning judgments into `working_inferences`.
- If an item could plausibly be challenged as not explicitly stated, treat it as inference, not fact.

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
