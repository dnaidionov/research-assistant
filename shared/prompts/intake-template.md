# Intake Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Job Directory: `{job_dir}`
Expected Output: `{stage_output_path}`

## Objective

Normalize the brief into an execution-ready intake record without adding external facts.

## Rules

- Do not invent evidence, sources, or conclusions.
- Keep missing information explicit.
- Convert ambiguous scope into concrete questions to resolve later.
- Preserve the distinction between provided facts and working assumptions.

## Required Output Format

Return JSON with these top-level keys:

- `question`
- `scope`
- `constraints`
- `assumptions`
- `missing_information`
- `required_artifacts`
- `notes_for_researchers`

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
