# Intake Stage Prompt

Fixture Family: hardware-tradeoff
Stable Qualification Fixture: intake
Stage ID: `intake`
Run ID: `qualification-fixture`
Job Directory: `/tmp/qualification-fixture/job`
Expected Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/01-intake.json`

## Source Materials

### brief.md

```markdown
# Hardware Tradeoff Brief

## Question
Should the portable scanner use an integrated compute module or external host processing?

## Constraints
- Power budget is limited.
- Field reliability matters more than peak throughput.
```

### config.yaml

```yaml
topic: qualification-fixture-hardware
requirements:
  require_citations: true
```
