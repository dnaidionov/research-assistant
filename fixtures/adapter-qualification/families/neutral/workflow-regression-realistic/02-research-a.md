# Research Stage Prompt

Fixture Family: neutral
Stable Qualification Fixture: research
Stage ID: `research-a`
Run ID: `qualification-fixture`
Role: `Research Pass A`
Depends On: `intake`
Expected Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/02-research-a.md`
Expected Structured Output: `/tmp/qualification-fixture/runs/run-001/stage-outputs/02-research-a.json`
Run Source Registry: `/tmp/qualification-fixture/runs/run-001/sources.json`

## Role Mandate

Cover the full research question, with extra depth on established, proven solutions: mature offerings with real deployment track records, documented limitations, and verifiable performance evidence. Still apply the Candidate Coverage Rules in full; depth of vetting, not narrow coverage, is what distinguishes this pass.

## Source Materials

### brief.md

```markdown
# Neutral Research Brief

## Question
Which of two documented implementation approaches is safer to recommend?

## Current State
- Team alpha currently uses a manual review path.
- Team beta proposes a partially automated path.

## Decision Pressure
- Reliability matters more than novelty.
```

### config.yaml

```yaml
topic: qualification-fixture-neutral
requirements:
  require_citations: true
  preserve_uncertainty: true
```

## Upstream Stage Artifacts

Use the output artifact from the dependency stage, not the dependency prompt packet.

- `/tmp/qualification-fixture/runs/run-001/stage-outputs/01-intake.json`
