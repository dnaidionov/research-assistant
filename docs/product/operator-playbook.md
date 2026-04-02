# Operator Playbook

## Purpose

This is the shortest control-plane reference for running and debugging the workflow as it exists today.

## Path Layout

Default local paths are:

- assistant repo: `~/Projects/research-hub/research-assistant`
- jobs root: `~/Projects/research-hub/jobs`

Those are defaults only. `jobs_root` is configured in `config/paths.yaml`. `jobs-index/` remains fixed inside the assistant repo.

## Manual Stage Recording

If you execute a stage manually, record what you actually attempted:

```bash
python3 scripts/record_manual_stage.py \
  --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001 \
  --stage judge \
  --status failed \
  --provider-key claude_research \
  --adapter claude \
  --model claude-sonnet-4-6
```

This is not optional bookkeeping. Failed and cancelled attempts still need provider/model attribution or the audit trail becomes misleading.

If you want the framework to launch only one stage, use:

```bash
python3 scripts/run_stage.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --stage research-b
```

Per-step overrides are supported through `--provider-key`, `--adapter`, and `--model`.

## Provider Trust

Trust tiers:

- `structured_safe_smoke`
- `structured_safe_regression`
- `structured_safe_realistic`

Set them in `config.yaml` through:

- `workflow.execution.required_provider_trust`
- `workflow.execution.stage_required_provider_trust`

## Provider Runtime Policy

Provider runtime scorecards live under:

- `audit/provider-scorecards/`

They now record:

- qualification history
- stage outcomes
- repair attempts
- live-drift outcomes
- quarantine state

Scorecards are execution evidence, not resume bookkeeping. Re-entering a completed run does not append synthetic `completed` outcomes for skipped stages.

Optional runtime policy lives under:

- `workflow.execution.provider_runtime_policy`

Use it to:

- quarantine providers after repeated failures or live-drift regressions
- reroute named stages through configured fallback providers

Inspect scorecards with:

```bash
python3 scripts/provider_scorecards_report.py --job-dir ~/Projects/research-hub/jobs/my-project-1
```

## Fixture Families

Current fixture families:

- `neutral`
- `hardware-tradeoff`
- `policy-analysis`

If a new research area does not fit an existing family, keep using `neutral` first and add a new family instead of mutating the default baseline.

Scaffold a new family with:

```bash
python3 scripts/create_fixture_family.py my-new-family
```

## Live Drift

Run a drift check against a stable sanitized reference job with:

```bash
python3 scripts/run_live_drift_check.py --fixture-family neutral
```

This now:

- executes the real workflow on a copied reference job
- writes `live-drift-report.json`
- updates provider scorecards only for providers actually observed in that drift run, not every provider declared in the copied job config

## Transactional Replay

Run state now has two layers:

- durable journal: `runs/<run-id>/events.jsonl`
- derived snapshot: `runs/<run-id>/workflow-state.json`

Rebuild the snapshot with:

```bash
python3 scripts/rebuild_workflow_state.py --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001
```

During replay, `stage_started`, `substep_started`, and `post_processing_started` events are restored as in-memory `running` state. That is deliberate; a rebuilt active run should not fall back to `scaffolded` only because the snapshot was missing.

During live execution, parallel stage groups now serialize snapshot mutations through one shared runner lock. The event journal is still the durable control plane, but the live `workflow-state.json` path is no longer updated concurrently by sibling stage workers.

Provider scorecards also record only one adapter outcome per execution attempt. If adapter execution completes and later claim extraction fails, the run still fails, but the provider is not double-counted as both `completed` and `failed` for that same attempt.

Likewise, a structured-stage repair that returns success but still leaves the required JSON artifact missing is treated as a hard failure. The runner does not reinterpret that as cancellation unless the stage was actually interrupted by sibling failure.

## Quality Benchmarks

Quality gates are configured through `quality_policy` and benchmarked through frozen fixtures.

Run the benchmark family with:

```bash
python3 scripts/run_quality_benchmarks.py --family neutral
```

Current benchmarked failure modes include:

- one-sided source selection
- recommendation support from disfavored evidence
- missing required comparison dimensions
- evidence-quality mismatch
- disagreement collapse
