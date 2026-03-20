# Judge Synthesis Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`

## Objective

Synthesize research pass A, research pass B, and both critiques into a judge report that keeps the reasoning auditable.

## Non-Negotiable Rules

- Separate supported conclusions from unresolved disagreements.
- Never erase disagreement just to make the output cleaner.
- Every factual claim must remain cited.
- Label inferences and confidence explicitly.
- Keep a traceable path from synthesis back to the research passes and critiques.

## Required Output Sections

1. Supported conclusions
2. Disagreements preserved
3. Confidence assessment
4. Evidence gaps
5. Recommended final artifact structure

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
