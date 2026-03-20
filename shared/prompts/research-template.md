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
- Separate facts from inferences in distinct sections.
- Record open questions and evidence gaps explicitly.
- Do not speculate beyond what the cited material supports.
- If evidence conflicts, preserve the conflict instead of smoothing it over.

## Required Output Sections

1. Executive summary
2. Facts
3. Inferences
4. Evidence gaps
5. Preliminary disagreements or uncertainties
6. Source evaluation notes

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
