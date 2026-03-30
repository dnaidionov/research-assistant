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

That default split is now only the fallback. `config.yaml` may define named providers under `workflow.execution.providers` and map stages to them through `workflow.execution.stage_providers`, so stage-provider and stage-model selection can live in the job repo instead of the runner code. Claude is now available as an additional adapter, and explicit model overrides are accepted only for adapters that support them. Before execution, the runner now qualifies each configured provider and records the result under `runs/<run-id>/audit/adapter-qualification/`; qualification now covers intake JSON, structured source-pass JSON, structured claim-pass JSON, and markdown materialization, and intake plus every structured stage require provider trust rather than only a coarse class. The default trust floor is `structured_safe_smoke`, but jobs can now require `structured_safe_regression` or `structured_safe_realistic` globally or per stage. For stronger operator checks, `scripts/qualify_adapters.py --profile workflow-regression --only-if-stale` extends the probes to critique and judge claim-pass behavior, renders those probes from sanitized real prompt packets, and reruns only when watched prompts, schemas, scripts, or the job config changed. A stronger `workflow-regression-realistic` profile now uses frozen sanitized fixture families under `fixtures/adapter-qualification/families/`, with `neutral` as the default baseline and `hardware-tradeoff` plus `policy-analysis` as current extensions. `scripts/run_live_drift_check.py` can exercise the full workflow against a stable reference-job family under `fixtures/reference-job/families/`, update provider scorecards for the copied job, and emit a scorecard summary in the drift report. `scripts/create_fixture_family.py <family>` now scaffolds a new family from the neutral baseline. If a future research area does not fit any current family, keep using `neutral` first and add a new family instead of mutating the default baseline. Provider behavior is now tracked under `audit/provider-scorecards/`, and `workflow.execution.provider_runtime_policy` can quarantine repeatedly failing providers and reroute specific stages through named fallbacks when the job allows it.
`execute_workflow.py` also now defaults the run id to the next incremental `run-###` name when `--run-id` is omitted. When an explicit run id already exists, it prompts for confirmation before continuing instead of silently resuming.

The runner is file-driven and resume-safe. Intake, research, critique, and judge now all run through decomposed internal substeps. Intake is split into source declaration, direct fact lineage, normalization, and merge before `01-intake.json` is accepted. Research, critique, and judge run as source-pass JSON, claim-pass JSON, bounded validator-driven repair where needed, and deterministic markdown rendering from the validated structured payload. Source-pass and claim-pass are now strict boundaries rather than soft hints: source-pass may emit only `stage` plus `sources`, and claim-pass must omit `sources`. Structured substeps now write any adapter-facing scratch markdown under `audit/substeps/`; final `stage-outputs/*.md` remains runner-owned. A shared stage-validation path handles source-aware JSON validation, markdown-contract backstops, canonical markdown regeneration, and structured claim-map generation for those stages. Structured stages no longer synthesize authoritative JSON from markdown, and the runner no longer parses authoritative artifacts out of stdout. Instead, adapter executors deterministically materialize outputs: exact JSON for structured outputs, raw stdout only for markdown outputs where that adapter mode is explicitly supported. Antigravity remains supported as an alternate adapter, but it cannot participate in structured execution unless it qualifies as `structured_safe`.
The runner now also persists run-level usage telemetry under `audit/usage/`. Execution-stage attempts, structured substages, and post-processing steps are tracked separately from qualification probes so workflow cost tuning is not polluted by provider-preflight overhead. Token counts are opportunistic exact telemetry only: when a CLI does not expose usage, records remain explicit with `usage_status: unavailable` rather than silently estimating or fabricating totals.
Structured research, critique, and judge claims may now include typed `support_links`, which lets the claim-map builder distinguish semantic evidence, context, challenge, and provenance roles on the structured path instead of relying only on flat citation markers. Local reasoning dependencies are modeled separately through `claim_dependencies` so fact IDs and source IDs are not conflated.
The runner now also enforces the rule that evidence is never implicit: each fact and each world-claim inference or synthesis item must carry explicit evidence on that exact item, and nearby citations do not count. When a structured stage output is close but contract-invalid, the runner gives it one bounded repair attempt using the exact validator errors; missing or unreadable structured output does not get a repair retry. In parallel stage groups, the runner now cancels sibling subprocesses after the first fatal failure and records interrupted siblings as `cancelled`. Decomposed structured stages now resume at substep granularity instead of always restarting from source-pass.
Driver logs record the invoked command, return code, stdout, stderr, output-path status, and a preview of the generated artifact so placeholder or misdirected-output failures can be diagnosed after the fact.
`workflow-state.json` now advances to terminal run-level statuses such as `completed` and `failed` instead of remaining stuck at `scaffolded` after execution.
Final-artifact readiness and final-artifact generation now share one publication-validation path, and markdown-only claim extraction can optionally consult the run-level source registry so provenance-versus-evidence classification follows source classes when registry data is available. Structured sidecars, standalone extraction, readiness checks, and publication now all share the same canonical claim-register summary logic. `quality_policy` now participates in readiness/publication checks, and `scripts/run_quality_benchmarks.py` evaluates stable benchmark fixtures under `fixtures/benchmarks/families/` so those quality gates remain regressible.
Judge outputs may now also include optional requester-facing `brief_improvements`. The judge markdown bridge can round-trip that section back into structured JSON, and final artifact generation inserts it after confidence and before references without reordering the required sections.

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
