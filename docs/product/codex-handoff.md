# Codex Handoff

## Objective

Turn the repository into a usable orchestration framework for structured multi-stage research runs.

## Current Architecture

- `~/Projects/research-hub/research-assistant/` = framework repo
- `~/Projects/research-hub/jobs/<job-name>/` = one independent repo per research job

## Implemented v1 Scope

The current v1 now supports:

1. validating job repos
   including repo-boundary, readability, runs-path, and template-doc consistency checks
2. scaffolding workflow runs by job name or job path
3. rendering prompt packets for the six core execution stages
4. writing workflow state and work orders
5. generating placeholder stage outputs
6. scaffolding authoritative structured JSON outputs for research, critique, and judge stages plus a run-level `sources.json`
7. scaffolding research, critique, and judge claim-sidecar targets inside each run
8. extracting atomic claims from markdown into a claim register with stable `C001`-style IDs and separated provenance/evidence markers
9. generating a downstream structured final artifact with external references only
10. automating the current adapter-driven execution split through a separate workflow runner
11. preserving audit artifacts inside the job repo

The current default automated split is:

1. `intake` in Codex
2. `research-a` in Codex and `research-b` in Gemini in parallel
3. `critique-a-on-b` in Codex and `critique-b-on-a` in Gemini in parallel
4. `judge` in Gemini
5. structured-output validation and stage claim sidecar generation for `research-a`, `research-b`, both critiques, and `judge`
6. claim extraction
7. final artifact generation

That default split is now only the fallback. `config.yaml` may define named providers under `workflow.execution.providers` and map stages to them through `workflow.execution.stage_providers`, so stage-provider and stage-model selection can live in the job repo instead of the runner code. Claude is now available as an additional adapter, and explicit model overrides are accepted only for adapters that support them.
`execute_workflow.py` also now defaults the run id to the next incremental `run-###` name when `--run-id` is omitted. When an explicit run id already exists, it prompts for confirmation before continuing instead of silently resuming.

The runner is file-driven and resume-safe. Intake is still a single-pass stage, but structured research, critique, and judge stages now run as a decomposed pipeline: source-pass JSON, claim-pass JSON, bounded validator-driven repair where needed, and deterministic markdown rendering from the validated structured payload. Source-pass and claim-pass are now strict boundaries rather than soft hints: source-pass may emit only `stage` plus `sources`, and claim-pass must omit `sources`. Structured substeps now write any adapter-facing scratch markdown under `audit/substeps/`; final `stage-outputs/*.md` remains runner-owned. A shared stage-validation path handles source-aware JSON validation, markdown-contract backstops, canonical markdown regeneration, and structured claim-map generation for those stages. Structured stages no longer synthesize authoritative JSON from markdown; if JSON is missing, that is a contract failure unless recoverable structured JSON appears in stdout. For stdout-oriented chat adapters such as Gemini and Antigravity, the runner can still recover structured JSON or markdown from stdout as a compatibility path. Antigravity remains supported as an alternate adapter.
Structured research, critique, and judge claims may now include typed `support_links`, which lets the claim-map builder distinguish semantic evidence, context, challenge, and provenance roles on the structured path instead of relying only on flat citation markers. Local reasoning dependencies are modeled separately through `claim_dependencies` so fact IDs and source IDs are not conflated.
The runner now also enforces the rule that evidence is never implicit: each fact and each world-claim inference or synthesis item must carry explicit evidence on that exact item, and nearby citations do not count. When a structured stage output is close but contract-invalid, the runner gives it one bounded repair attempt using the exact validator errors; missing or unreadable structured output does not get a repair retry. In parallel stage groups, the runner now cancels sibling subprocesses after the first fatal failure and records interrupted siblings as `cancelled`. Decomposed structured stages now resume at substep granularity instead of always restarting from source-pass.
Driver logs record the invoked command, return code, stdout, stderr, output-path status, and a preview of the generated artifact so placeholder or misdirected-output failures can be diagnosed after the fact.
`workflow-state.json` now advances to terminal run-level statuses such as `completed` and `failed` instead of remaining stuck at `scaffolded` after execution.

## Canonical Research Lifecycle

1. intake
2. research pass A
3. research pass B
4. critique of A on B
5. critique of B on A
6. judge
7. claim extraction
8. artifact writing

`scripts/run_workflow.py` currently scaffolds stages 1 through 6. `scripts/execute_workflow.py` can now run those six stages with the current adapter-driven split and then trigger downstream claim extraction and artifact writing.

## Constraints

- Do not collapse assistant and jobs into one repo.
- Do not remove the dual research passes, dual critiques, or judge stage.
- Do not assume a single model or provider.
- Do not store real research data in the assistant repo.
- Prefer plain files over opaque storage.

## Expected Artifacts Per Run

Inside a job repo:

- `runs/<run-id>/prompt-packets/`
- `runs/<run-id>/stage-outputs/`
- `runs/<run-id>/stage-claims/`
- `runs/<run-id>/sources.json`
- `runs/<run-id>/workflow-state.json`
- `runs/<run-id>/WORK_ORDER.md`
- `runs/<run-id>/audit/`
- `runs/<run-id>/logs/`

At the job root:

- `outputs/`
- `evidence/`
- `audit/`
- `logs/`

## Still Out Of Scope

- provider API integration
- automatic web retrieval
- automated citation verification
- UI
