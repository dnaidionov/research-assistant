# Critique Stage Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Critic Role: `{critic_label}`
Target Role: `{target_label}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`

## Objective

Critique the target research pass adversarially. The goal is to find unsupported claims, weak evidence, missing alternatives, and places where inference is presented too confidently.

## Non-Negotiable Rules

- Do not rewrite the target report into agreement.
- Preserve disagreements and unresolved conflicts.
- Quote the exact claim IDs or passages being challenged where possible.
- Distinguish between invalid claims, weakly supported claims, and reasonable but incomplete claims.

## Required Output Sections

1. Strong claims that survive review
2. Unsupported or weakly supported claims
3. Missing counterarguments or alternative explanations
4. Citation quality concerns
5. Disagreements to preserve for the judge

## Source Materials

### brief.md

```markdown
{brief_markdown}
```

### config.yaml

```yaml
{config_yaml}
```
