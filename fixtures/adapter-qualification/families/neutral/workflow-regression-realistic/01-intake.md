# Intake Stage Prompt

Fixture Family: neutral
Stable Qualification Fixture: intake
Stage ID: `intake`
Run ID: `qualification-fixture`
Job Directory: `/tmp/qualification-fixture/job`
Expected Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/01-intake.json`

## Objective

Normalize the brief into an execution-ready intake record without adding external facts.

## Source Materials

### brief.md

```markdown
# Neutral Research Brief

## Question
Which of two documented implementation approaches is safer to recommend?

## Current State
- Team alpha currently uses a manual review path.
- Team beta proposes a partially automated path.

## Constraints
- Keep evidence explicit.
- Preserve uncertainty.
```

### config.yaml

```yaml
topic: qualification-fixture-neutral
requirements:
  require_citations: true
  preserve_uncertainty: true
```
