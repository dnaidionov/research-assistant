# Research Stage Prompt

Fixture Family: neutral
Stable Qualification Fixture: research
Stage ID: `research-b`
Run ID: `qualification-fixture`
Role: `Research Pass B`
Depends On: `intake`
Expected Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/03-research-b.md`
Expected Structured Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/03-research-b.json`
Run Source Registry: `/tmp/qualification-fixture/runs/run-001/sources.json`

## Source Materials

### brief.md

```markdown
# Neutral Research Brief

## Question
Which of two documented implementation approaches is safer to recommend?
```

### config.yaml

```yaml
topic: qualification-fixture-neutral
requirements:
  require_citations: true
```

## Upstream Stage Artifacts

Use the output artifact from the dependency stage, not the dependency prompt packet.

- `/tmp/qualification-fixture/runs/run-001/stage-outputs/01-intake.json`
