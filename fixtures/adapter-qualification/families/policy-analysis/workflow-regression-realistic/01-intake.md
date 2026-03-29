# Intake Stage Prompt

Fixture Family: policy-analysis
Stable Qualification Fixture: intake
Stage ID: `intake`
Run ID: `qualification-fixture`
Job Directory: `/tmp/qualification-fixture/job`
Expected Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/01-intake.json`

## Source Materials

### brief.md

```markdown
# Policy Analysis Brief

## Question
Which reporting policy is safer to recommend under incomplete evidence?

## Constraints
- Preserve disagreement.
- Separate findings from recommendations.
```

### config.yaml

```yaml
topic: qualification-fixture-policy
requirements:
  require_citations: true
```
