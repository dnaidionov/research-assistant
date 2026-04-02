# Installation and Configuration

## Purpose

This guide covers local installation, path configuration, authentication, and the practical setup required to run the framework.

## Default Layout

The default layout is:

- assistant repo: `~/Projects/research-hub/research-assistant`
- jobs root: `~/Projects/research-hub/jobs`

Those are defaults, not hard requirements.

`jobs-index/` is different. It is fixed inside the assistant repo and is not meant to be relocated.

## Path Configuration

The assistant repo now carries a committed path config at:

- `config/paths.yaml`

Default contents:

```yaml
assistant_root: ~/Projects/research-hub/research-assistant
jobs_root: ~/Projects/research-hub/jobs
```

Behavior:

- `jobs_root` is configurable
- `jobs-index/` remains fixed inside the assistant repo
- local scripts always use the real repo location at runtime
- a custom `assistant_root` is validated against the actual repo location
- the shipped default `assistant_root` is treated as a documented default and does not block CI or non-default checkouts

That distinction exists for a reason. The assistant repo can derive its own true location at runtime. The shipped `~/Projects/...` value is a default, not a contract. But if you customize `assistant_root`, the safer behavior is still to fail clearly when that custom path no longer matches reality.

## Basic Local Setup

1. Clone the assistant repo.
2. Review and, if necessary, edit `config/paths.yaml`.
3. Create the jobs root if it does not exist.
4. Install dashboard dependencies if you want the browser UI:

```bash
cd ~/Projects/research-hub/research-assistant/dashboards/ui
npm install
```

5. Start the dashboard when needed:

```bash
npm run dev
```

The dashboard is browser-based but local. It runs on the user’s machine and operates on local job repos.

## Job Creation and Validation

Create a job:

```bash
cd ~/Projects/research-hub/research-assistant
./scripts/create_job.sh my-project-1
```

Validate it:

```bash
python3 scripts/validate_job.py --job-dir ~/Projects/research-hub/jobs/my-project-1
```

## Scaffold a Run

```bash
python3 scripts/run_workflow.py --job-path ~/Projects/research-hub/jobs/my-project-1 --run-id run-001
```

You can also resolve by:

- `--job-name`
- `--job-id`

Those resolve through the fixed assistant-repo `jobs-index/`.

## Manual Mode

Manual mode means the operator executes stages themselves from the rendered prompt packets and then records what actually happened.

Two options:

- execute outside the framework and record the attempt with `scripts/record_manual_stage.py`
- launch one stage through `scripts/run_stage.py`

### Recording a Manual Attempt

```bash
python3 scripts/record_manual_stage.py \
  --run-dir ~/Projects/research-hub/jobs/my-project-1/runs/run-001 \
  --stage research-b \
  --status failed \
  --provider-key claude_research \
  --adapter claude \
  --model claude-sonnet-4-6
```

This records:

- stage status
- attempted provider key
- attempted adapter
- attempted model
- run-level actual stage assignment
- usage telemetry with `usage_status: unavailable`

Failed and cancelled attempts still preserve attempted provider/model. That is deliberate. Audit trails are not useful if they only record successful execution.

### Launching One Stage

```bash
python3 scripts/run_stage.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --stage research-b
```

Per-step override is supported:

```bash
python3 scripts/run_stage.py \
  --job-path ~/Projects/research-hub/jobs/my-project-1 \
  --run-id run-001 \
  --stage research-b \
  --adapter claude \
  --model claude-sonnet-4-6 \
  --provider-key manual_claude_override
```

Override precedence is:

1. explicit step override
2. job config stage provider/model
3. fallback CLI split when no job execution config exists

## Automated Mode

Run the current 2-pass workflow:

```bash
python3 scripts/execute_workflow.py --job-path ~/Projects/research-hub/jobs/my-project-1 --run-id run-001
```

Automated runs now persist:

- configured stage assignments
- resolved stage assignments
- actual attempted stage assignments

in:

- `runs/<run-id>/audit/execution-config.json`

That distinction matters when a manual or launched step overrides the configured provider/model.

## GitHub Authentication

GitHub auth is needed when you want the framework or dashboard to:

- create repos
- push branches
- open or merge PRs
- rely on git-backed job and dashboard workflows

Without GitHub auth, local file-based orchestration still works, but repo automation and GitHub-backed workflows do not.

Typical local setup:

```bash
gh auth login
```

## LLM Provider Authentication

Provider auth is needed for:

- adapter qualification
- manual single-stage launching
- full automated execution
- drift checks that use real providers

Without provider auth, you can still scaffold runs and inspect artifacts, but you cannot execute real model stages.

Practical examples:

- Codex CLI must be authenticated before `codex exec` works
- Claude CLI must be authenticated before `claude -p ...` works

Exact provider setup can change over time, so the principle matters more than hardcoded vendor steps: execution requires authenticated CLIs.

## Costs

This workflow can incur real LLM usage costs.

That is not accidental. The system deliberately spends more calls than one-shot prompting because it is buying:

- independent passes
- adversarial critique
- judgment
- structured validation
- auditable outputs

If cost sensitivity matters, tune:

- provider choice
- model size
- prompt size
- workflow shape
- qualification frequency

## Secrets Guidance

Do not commit:

- provider tokens
- GitHub tokens
- local auth material
- machine-specific secret values

Neither the assistant repo nor job repos should store credentials in tracked config.
