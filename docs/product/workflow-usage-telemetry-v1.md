# Plan: workflow-usage-telemetry-v1

## Goal

Add per-stage and per-substage usage telemetry to workflow runs, so run reports show resource usage for successful and failed executions and support prompt and architecture tuning later.

## Why this plan

- helps identify expensive stages
- supports tuning prompts and decomposition strategy
- makes failures measurable, not just visible
- should be added in an adapter-agnostic way

## Non-goal

Do not pretend all adapters provide exact token counts. v1 must distinguish:

- reported usage
- estimated usage
- unavailable usage

That distinction is mandatory.

## Design Decision

Implement usage tracking in two layers:

1. execution telemetry schema now
2. token metrics opportunistically

Execution telemetry should always record attempt metadata, duration, prompt size, output size, and adapter/model identity.

Token metrics should be exact only when the adapter or CLI exposes them. When they are not available, the system should leave token counts null rather than fabricating exact values. Estimated token counting can come later as a separate field family.

## Scope

Change:

- adapter execution result schema
- run logs and run audit artifacts
- workflow-state or run-report summary
- docs
- tests

Do not change:

- workflow stage graph
- provider-selection architecture
- publication or claim semantics

## Required Output

Each run should expose usage data for:

- every stage
- every structured substage where applicable
- successful runs
- failed runs
- qualification separately from execution

## Data Model

Add a usage record shape like:

```json
{
  "scope": "stage",
  "stage_id": "research-b",
  "substep": "claim-pass",
  "provider_key": "claude_sonnet",
  "adapter": "claude",
  "model": "claude-sonnet-4-6",
  "status": "completed",
  "usage_status": "reported",
  "started_at": "2026-03-29T12:00:00Z",
  "finished_at": "2026-03-29T12:00:08Z",
  "duration_ms": 8123,
  "prompt_chars": 14231,
  "prompt_bytes": 14231,
  "stdout_bytes": 5120,
  "stderr_bytes": 0,
  "input_tokens": 3201,
  "output_tokens": 811,
  "total_tokens": 4012,
  "estimated_input_tokens": null,
  "estimated_output_tokens": null,
  "estimated_total_tokens": null,
  "attempt_index": 1,
  "failure_reason": null
}
```

Allowed `usage_status` values:

- `reported`
- `estimated`
- `unavailable`

For v1, the common cases are expected to be:

- `reported`
- `unavailable`

## Separation Rule

Qualification usage must be stored separately from execution usage.

Reason:

- qualification cost is operational overhead
- execution cost is workflow cost
- mixing them corrupts tuning data

## Artifact Layout

Recommended:

- detailed telemetry:
  - `runs/<run-id>/audit/usage/usage-records.json`
- summarized telemetry:
  - `runs/<run-id>/audit/usage/usage-summary.json`

Optional:

- expose a condensed summary inside `workflow-state.json`

But the detailed records should remain in audit artifacts.

## What to Record

For each attempt:

- stage id
- substep if present
- provider key
- adapter
- model
- status
- timestamps
- duration
- prompt chars and bytes
- stdout bytes
- stderr bytes
- token fields if available
- failure reason if non-success
- retry or repair attempt index if relevant

For structured stages:

- `source-pass`
- `claim-pass`
- `render`

For intake:

- `source-pass`
- `fact-lineage`
- `normalization`
- `merge`

For qualification:

- provider key
- probe name
- profile
- the same usage envelope

But qualification usage must remain separate from stage execution usage.

## Implementation Steps

1. Extend command execution result model

- File: [`scripts/execute_workflow.py`](/Users/Dmitry_Naidionov/Projects/research-hub/research-assistant/scripts/execute_workflow.py)
- Ensure adapter executor returns:
  - timestamps
  - duration
  - prompt size
  - stdout and stderr size
  - token fields if known
  - model and provider metadata

2. Add usage persistence helpers

- Likely a new helper file or new workflow execution helpers
- Write append-safe usage records into:
  - `audit/usage/usage-records.json`
  - `audit/usage/usage-summary.json`

3. Record stage and substage attempts

- intake substeps
- structured stage substeps
- markdown-only stages where relevant
- failures included

4. Record qualification separately

- File: [`scripts/_adapter_qualification.py`](/Users/Dmitry_Naidionov/Projects/research-hub/research-assistant/scripts/_adapter_qualification.py)
- capture usage per probe
- persist under qualification usage artifacts
- do not merge into stage totals

5. Add run summary rollups

- totals by:
  - stage
  - substage
  - provider
  - adapter
  - model
- split:
  - reported totals
  - estimated totals
  - unavailable counts

6. Update logs and reporting

- make the run report surface:
  - which stages had usage
  - which stages are missing usage
  - total reported token usage where available
  - execution duration by stage and substage

7. Document exact vs estimated policy

- README
- automation workflow docs
- product spec

## Token Source Policy

Reported tokens:

- use only provider or CLI reported numbers when clearly available and attributable

Estimated tokens:

- not required in v1
- if added later, keep separate fields:
  - `estimated_input_tokens`
  - `estimated_output_tokens`
  - `estimated_total_tokens`

Unavailable:

- if no exact usage exists, keep token fields null and mark `usage_status: unavailable`

## Failure Handling

Usage records must be written even when:

- adapter exits non-zero
- structured artifact is invalid
- repair fails
- provider times out
- provider is cancelled

This is one of the main reasons to build the telemetry layer.

## Questions the Report Should Answer

- Which stage uses the most tokens?
- Which substage is disproportionately expensive?
- Which adapter or model is driving cost?
- Are failures clustering in expensive stages?
- Is qualification overhead materially affecting runs?
- Are structured substeps cheaper or costlier than expected?

## Tests to Add

1. Positive execution telemetry

- successful stage writes a usage record
- structured stages write substage usage records
- summary totals are computed

2. Failure telemetry

- failed stage still writes usage record
- cancelled sibling writes usage record with terminal status
- repair attempts produce distinct usage records

3. Qualification telemetry

- probe usage is recorded
- qualification totals remain separate from execution totals

4. Policy tests

- unavailable token counts remain null
- reported vs unavailable states are preserved
- no fake token counts appear when adapter provides none

5. Reporting tests

- summary aggregates by stage and provider
- summary includes missing-usage counts

## Recommended v1 Constraints

- do not block workflow completion just because token data is unavailable
- do not estimate silently
- do not combine qualification and execution totals
- do not store usage only in freeform logs

## Risks

- adapters may expose little or no usage data
- token comparability across providers may stay imperfect
- telemetry can become noisy if retries are not modeled clearly

## Mitigations

- treat usage as structured telemetry, not just tokens
- separate attempts cleanly
- separate reported from estimated
- separate qualification from execution

## Success Criteria

- every run has usage artifacts
- every stage and substage attempt is represented
- failures are included
- reported token counts appear where available
- missing token data is explicit, not hidden
- docs match implementation

