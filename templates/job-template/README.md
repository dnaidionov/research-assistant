# Job Template

This directory is copied into a new job repo under the configured jobs root.

Default path:

- `~/Projects/research-hub/jobs/<job-name>/`

That is only the default. The actual jobs root is configured in the assistant repo via `config/paths.yaml`.

## Required Files

- `brief.md` - research question, scope, and deliverables
- `config.yaml` - execution and evidence constraints

## Required Directories

- `runs/` - one subdirectory per workflow run
- `outputs/` - promoted deliverables for the job
- `evidence/` - claim registers, source notes, and evidence logs
- `audit/` - validation outputs and cross-run audit artifacts
- `logs/` - execution logs

## Rules

- Keep all research artifacts inside the job repo.
- Keep disagreements visible until a judge stage resolves them.
- Do not add uncited factual claims to final outputs.
