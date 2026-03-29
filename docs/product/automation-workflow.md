# Automation Workflow

## Overview

The v1 workflow is a file-based orchestration pipeline executed by scripts and operated manually, semi-manually, or through a CLI-driven adapter runner.

The orchestration layer remains provider-agnostic. It prepares prompt packets, state files, work orders, and audit artifacts. It does not perform provider API calls in v1.

## Canonical Research Lifecycle

1. Intake
2. Research pass A
3. Research pass B
4. Critique of A by B
5. Critique of B by A
6. Judge
7. Claim extraction
8. Artifact writing

These stages must remain distinct. The workflow must not collapse research, critique, judge, and claim extraction into a single pass.

## `run_workflow.py` Scaffold Scope

`scripts/run_workflow.py` currently scaffolds the six execution-stage prompt packets:

1. Intake
2. Research A
3. Research B
4. Critique A on B
5. Critique B on A
6. Judge

Claim extraction and artifact writing remain separate downstream steps. That split is deliberate: the runner creates the auditable core research exchange first, while later transformations stay isolated in their own scripts.

## `execute_workflow.py` Automation Scope

`scripts/execute_workflow.py` automates the current 2-pass workflow through configurable CLI adapters.

The current fallback default adapter assignment is:

1. intake in Codex
2. research A in Codex and research B in Gemini in parallel
3. critique A on B in Codex and critique B on A in Gemini in parallel
4. judge in Gemini
5. structured-output validation and stage claim sidecar generation for research A, research B, both critique stages, and judge
6. claim extraction
7. final artifact generation

The runner is file-driven. It waits on required stage output artifacts, updates `workflow-state.json`, and writes per-step logs into the run directory.
For structured research, critique, and judge stages, it no longer relies on one monolithic model call. It now decomposes those stages into a source pass, a claim pass, and deterministic markdown rendering from the validated structured payload.
It also emits live stage progress. In interactive terminals it redraws status in place; in captured output it emits ordered start and completion events.
Antigravity remains available as an adapter option but is no longer the default secondary adapter.
Claude is now available as an additional stdout-oriented adapter option.

Job-level execution config may now override the fallback primary-secondary split. `config.yaml` may define:

- `workflow.execution.providers`
- `workflow.execution.stage_providers`
- `workflow.execution.required_provider_trust`
- `workflow.execution.stage_required_provider_trust`
- `workflow.execution.provider_runtime_policy`

Each named provider declares an `adapter` and may declare a `model` when that adapter supports explicit model selection. `stage_providers` then maps each execution stage to one of those named providers. This is now the preferred way to pin stage-provider and stage-model selection for a job.
The trust fields let a job demand stronger qualification depth globally or per stage instead of always accepting the default smoke-level trust.

`execute_workflow.py` still accepts `--run-id`, but it is no longer required. When omitted, the runner now chooses the next incremental run id under the job's `runs/` directory, ignoring non-incremental names such as `run-manual`. When an explicit `--run-id` already exists, the runner now asks for confirmation before continuing that run.

## Stage Intent

### 1. Intake
- normalize the brief
- identify missing information
- restate constraints without adding facts

### 2. Research pass A
- produce an independent research report
- separate facts and inference
- include inline citations
- use canonical external citation IDs for evidence, not ad hoc labels or stage references
- when structured JSON is available, attach typed `support_links` so evidence, context, challenge, and provenance are explicit rather than inferred later
- if a later claim depends on earlier local facts or conclusions, record those under `claim_dependencies` instead of misusing `support_links.source_id`
- if a fact or inference asserts a claim about the world, at least one supporting link must be role `evidence`; `context` alone is not enough to satisfy the semantic evidence requirement
- evidence is never implicit; a fact or inference cannot rely on nearby citations or earlier citations as support for a new item

### 3. Research pass B
- produce a second independent research report
- preserve independent reasoning from pass A
- follow the same canonical external citation scheme as pass A

### 4. Critique of A by B
- challenge unsupported claims in pass A
- preserve disagreements for adjudication
- emit a structured critique artifact alongside the markdown view

### 5. Critique of B by A
- challenge unsupported claims in pass B
- preserve disagreements for adjudication
- emit a structured critique artifact alongside the markdown view

### 6. Judge
- synthesize supported conclusions
- keep unresolved disagreements visible
- distinguish supported conclusions from open questions
- preserve external evidence citations from the research record instead of replacing them with stage references
- when structured JSON is available, carry typed support roles forward so the judge can separate world support from provenance semantically
- supported conclusions and synthesis judgments must each carry their own explicit evidence support; nearby citations do not count

### 7. Claim extraction
- convert markdown into a v1 claim register with stable `C001`-style IDs
- separate internal workflow provenance from external evidence sources where marker classification allows
- retain explicit markers such as citations and confidence where present
- treat the current output as a draft audit artifact, not as a fully reliable truth register

### 8. Artifact writing
- produce the final user-facing artifact
- use only cited claims from prior stages
- include summary, option comparison, recommendation, confidence or uncertainty, references, and open questions
- keep workflow provenance in audit artifacts, not in the user-facing references section

## Run Artifacts

Each run writes to `jobs/<job-name>/runs/<run-id>/`.

The run directory contains:

- `prompt-packets/`
- `stage-outputs/`
- `stage-claims/`
- `sources.json`
- `events.jsonl`
- `workflow-state.json`
- `WORK_ORDER.md`
- `audit/`
- `logs/`

The workflow script writes placeholder stage outputs as part of the scaffold so the run is auditable before any provider execution happens.

## Job-Level Artifacts

Each job repo also contains:

- `outputs/`
- `evidence/`
- `audit/`
- `logs/`

Promoted deliverables belong in those job-level directories, not in the assistant repo.

## Current Script Responsibilities

### `scripts/run_workflow.py`
- validates the job repo
- accepts a job name, a job id from `jobs-index` metadata, or an explicit job path
- creates a new run directory
- resolves job names and ids via `jobs-index/` or the jobs root
- renders prompt packets for the six execution stages
- writes explicit upstream stage-output artifact references into prompt packets and the work order
- scaffolds the run-level source registry at `sources.json`
- scaffolds structured JSON output targets for research A, research B, both critique stages, and judge
- writes `workflow-state.json`
- writes `WORK_ORDER.md`
- writes run audit files and placeholder output targets

### `scripts/execute_workflow.py`
- ensures the target run exists
- accepts a job name, a job id from `jobs-index` metadata, or an explicit job path
- chooses the next incremental `run-###` identifier automatically when `--run-id` is omitted, while still honoring an explicit `--run-id` when provided
- prompts for confirmation before continuing an explicitly targeted run that already exists
- resolves primary and secondary execution roles through named CLI adapters
- defaults to Codex as the primary adapter and Gemini as the secondary adapter when no job-level execution config is present
- now also supports Claude as an alternate adapter
- prefers job-level named-provider execution config over the CLI primary-secondary fallback when `workflow.execution` is defined
- qualifies each unique configured provider before execution and persists reports under `runs/<run-id>/audit/adapter-qualification/`
- requires provider trust rather than only a coarse classification for intake and all structured stages before those stages are allowed to run
- defaults to `structured_safe_smoke`
- can require `structured_safe_regression` or `structured_safe_realistic` through job config when a run needs a stronger gate
- uses multiple stage-like qualification probes rather than a single generic smoke test: intake JSON, research source-pass JSON, research claim-pass JSON, and markdown materialization
- supports a stronger `workflow-regression` qualification profile for operator and CI use, which extends the probe set to critique and judge claim-pass behavior
- renders those regression probes from sanitized real prompt packets for intake, research, critique, and judge instead of relying only on toy prompt strings
- supports `workflow-regression-realistic`, which uses frozen sanitized fixture packets under `fixtures/adapter-qualification/families/<family>/workflow-regression-realistic/`
- the default realistic fixture family is `neutral`
- current extension families include `hardware-tradeoff` and `policy-analysis`
- if a new research area does not fit an existing family, the workflow should continue using `neutral` by default while a new family is created and customized explicitly
- supports stale-aware reruns for regression qualification by fingerprinting `shared/prompts/`, `schemas/`, `scripts/`, and the target job's `config.yaml`
- fingerprints the realistic qualification fixtures and the stable reference job fixtures too, so stale detection now follows repo-side drift in those artifacts as well
- passes each tool explicit stage metadata including stage id, prompt-packet path, markdown output path, structured-output path where required, and source-registry path
- executes intake as:
  - source declaration
  - direct fact-lineage extraction
  - normalization
  - final merge into `01-intake.json`
- executes structured research, critique, and judge stages as:
  - source-pass JSON generation
  - claim-pass JSON generation
  - bounded validator-driven repair when either JSON pass is close but contract-invalid
  - deterministic markdown rendering from the validated structured payload
- enforces strict substep boundaries:
  - source-pass may emit only `stage` and `sources`
  - claim-pass must not emit `sources`
- gives structured substeps scratch markdown paths under `audit/substeps/` instead of letting them write directly into final `stage-outputs/*.md`
- uses deterministic adapter executors instead of runner-side artifact recovery
- for structured JSON outputs, adapters must either write the file directly or emit exact JSON that the adapter executor can materialize without heuristics; mixed chatter is a hard failure
- for markdown outputs, stdout-oriented adapters may still materialize raw stdout directly, but the runner no longer parses headings or fenced blocks out of stdout
- no longer synthesizes authoritative structured JSON from markdown for structured stages; missing JSON is now a hard contract failure
- reports stage start, completion, and failure status while the workflow runs
- executes the two research stages in parallel
- executes the two critique stages in parallel
- validates structured research, critique, and judge outputs against source-aware contracts before downstream execution continues
- gives each structured stage at most one bounded repair pass when the first adapter output is structurally close but contract-invalid
- does not spend a repair pass when a structured substep produced no usable JSON artifact at all; missing or unreadable structured output is treated as a hard substep failure
- applies a shared structured-stage validator that also repairs weak markdown bridge artifacts from authoritative JSON when possible
- validates the intake JSON stage against its own explicit contract before research can proceed
- merges stage-declared sources into the run-level `sources.json` registry and rejects unresolved source IDs
- treats `sources.json` as runner-owned state; stage agents may read it but should not modify it directly, and direct edits are discarded before merge
- normalizes source records into explicit source classes for downstream publication policy
- enriches normalized source records with first-pass evidence-policy metadata such as authority tier, evidence kind, freshness status, support flags, policy outcome, and policy notes
- rejects duplicate source IDs within a stage payload and warns when multiple external source IDs collapse onto the same locator
- emits source-quality warnings when external evidence uses only a bare domain locator or when `job_input` points to prompt-packet packaging instead of the underlying canonical artifact
- expects agents to retain the exact source locator they actually used; degrading a page URL to a site root or bare domain is treated as a source-quality defect, not acceptable normalization
- extracts claim sidecars for `research-a`, `research-b`, `critique-a-on-b`, `critique-b-on-a`, and `judge`
- uses structured judge JSON for automated claim-register generation when available
- keeps section-aware markdown validation as a migration backstop for research, critique, and judge contracts, but now through one shared stage-validation path
- keeps non-truth-critical narrative sections flexible in structured validation so usable research is not rejected over presentation-shape variance
- resolves local fact or conclusion IDs inside structured inference evidence lists back to canonical external source IDs before validation
- waits for judge completion before downstream processing
- cancels sibling subprocesses in the research and critique parallel groups after the first fatal stage failure and marks those interrupted siblings as `cancelled`
- runs claim extraction and final artifact generation automatically
- supports idempotent resume by skipping completed stage artifacts and downstream outputs
- resumes decomposed structured stages at substep granularity when a prior source-pass or claim-pass artifact is still valid
- journals run lifecycle transitions into append-only `events.jsonl`
- derives `workflow-state.json` from those durable events and current state transitions instead of treating the snapshot as the only source of truth
- updates workflow state and marks failed stages explicitly when an adapter exits non-zero or leaves placeholder output behind
- recomputes terminal run-level workflow status so completed runs do not remain marked as `scaffolded`
- writes per-stage driver logs with command, return code, stdout, stderr, output-path status, and output preview for troubleshooting
- rejects job-level provider configs that request explicit model selection for adapters that do not support it
- records provider qualification, stage outcomes, repair attempts, and live-drift history into `audit/provider-scorecards/`
- applies `workflow.execution.provider_runtime_policy` to quarantine repeatedly failing providers and reroute stages through named fallbacks when configured
- forwards `quality_policy` into final-artifact readiness and publication validation

### `scripts/qualify_adapters.py`
- probes a concrete adapter binary against deterministic markdown plus multiple stage-like structured fixture prompts
- classifies the adapter as `structured_safe`, `markdown_only`, or `unsupported`
- also reports a trust tier such as `structured_safe_smoke`, `structured_safe_regression`, or `structured_safe_realistic`
- can persist that report into a run's `audit/adapter-qualification/` directory
- supports `--profile smoke` and `--profile workflow-regression`
- also supports `--profile workflow-regression-realistic`
- the `workflow-regression` profile is now probe-set version `workflow-regression.v2` and treats critique and judge regression probes as part of the structured-safe decision rather than as informational extras
- `--min-trust` can now require a zero exit code only when the reported trust tier satisfies the requested floor
- supports `--only-if-stale` so persisted regression reports are reused until watched prompts, schemas, scripts, or job config inputs change
- exists primarily as a debugging and operator tool; `execute_workflow.py` runs the same qualification logic automatically before execution

### `scripts/run_live_drift_check.py`
- copies a stable sanitized reference job from `fixtures/reference-job/families/<family>/` into a temporary or operator-specified work root
- defaults to the `neutral` family unless `--fixture-family` or `--fixture-dir` is provided
- runs the real workflow against that copied fixture job
- relies on the fixture's `required_provider_trust: structured_safe_realistic` policy unless the copied config is edited
- writes `live-drift-report.json` into the resulting run's `audit/` directory
- updates provider scorecards for the copied reference job and includes a scorecard summary in the drift report
- exists to catch provider drift on a full live workflow path without using a real job repo

### `scripts/create_fixture_family.py`
- scaffolds a new fixture family by copying the `neutral` baseline into both:
  - `fixtures/adapter-qualification/families/<family>/`
  - `fixtures/reference-job/families/<family>/`
- exists so new research areas can start from a known-good neutral baseline instead of mutating the default fixtures directly

### `scripts/provider_scorecards_report.py`
- summarizes provider runtime scorecards for a job
- exists so operators can inspect quarantine state, failure totals, qualification history, repair attempts, and live-drift history without reading raw JSON directly

### `scripts/run_quality_benchmarks.py`
- evaluates stable quality benchmark fixtures under `fixtures/benchmarks/families/`
- exists so research-quality gates remain regressible instead of purely judgment-based

### CI Trigger
- `.github/workflows/adapter-regression.yml` now reruns the adapter-regression guard tests when prompts, schemas, scripts, tests, or the regression workflow definition itself change
- this does not replace live provider qualification; it protects the regression harness and stale-input logic inside the repo

### `scripts/extract_claims.py`
- parses markdown into atomic claims
- can consume structured stage JSON directly and build claim maps without markdown heuristics when the input is an authoritative stage artifact
- can consume the run-level source registry during markdown extraction so marker classification follows source classes when registry data is available
- uses the same canonical claim-register summary rules as structured stage sidecar generation, so markdown compatibility is now only an ingestion path into the same claim/publication model
- distinguishes truth-gated classes such as `fact`, `inference`, `decision`, and `recommendation` from non-gating adjudication classes such as `evaluation`, `open_question`, and `evidence_gap`
- assigns stable `C001`-style IDs
- separates bracketed markers into provenance, external evidence, and unclassified buckets
- preserves typed `support_links` from structured stage artifacts and derives semantic evidence versus provenance from those links plus source classes when they are present
- preserves `claim_dependencies` from structured stage artifacts so local reasoning traceability is kept distinct from source support
- captures explicit confidence labels when present
- classifies disagreements and confidence summaries as evaluation-oriented claims instead of defaulting them to facts
- can fail on uncited facts and uncited inferences in strict mode when used as a hard validator
- flags provenance-only supported facts for downstream gating
- rejects workflow-stage references as evidence citations
- still relies on lexical and markdown-structure heuristics for markdown-only inputs and compatibility paths

### `scripts/generate_final_artifact.py`
- reads the judge artifact and claim register
- applies the shared publication-validation rules before rendering
- uses the same canonical claim-register substrate as standalone extraction and structured stage sidecar generation
- rejects uncited facts, uncited inferences, provenance-only facts, and unclassified markers
- rejects uncited truth-gated claims and unsupported recommendations that carry evidence but no explicit rationale or risk accounting
- rejects referenced provisional or workflow-provenance sources when structured source records are available
- rejects referenced sources whose normalized `policy_outcome` is `blocked`, and includes policy notes in that failure path
- rejects unresolved referenced source IDs instead of emitting bare IDs into the final report
- writes a structured final artifact with external references only
- keeps workflow provenance out of the user-facing references section

## Intake State

The intake contract now emits source-backed `known_facts` plus an intake-declared `sources` list and a short `source_excerpt` and stable `source_anchor` for each fact. Intake is no longer executed as one opaque model call. The runner now splits it into source declaration, direct fact lineage, normalization, and merge. That materially reduces the old ambiguity between direct brief facts and intake-stage paraphrase, even though richer machine-readable span provenance is still a future refinement rather than a current requirement.

### `scripts/validate_job.py`
- validates that a job repo has the required files and directories
- checks that the job is separate from the assistant repo
- checks that key config and artifact files are readable
- validates that `runs/` is a usable directory path
- checks that job-template requirements remain consistent with product docs
- can validate minimum readiness for final artifact generation using the same publication rules as the final artifact generator
- uses structured judge references for readiness checks when a sibling judge JSON artifact is available, so readiness and publication no longer disagree about unresolved references
- returns structured validation results with explicit exit codes

### `scripts/rebuild_workflow_state.py`
- rebuilds `workflow-state.json` from `events.jsonl`
- exists for crash recovery, stale-snapshot recovery, and audit inspection
- treats the event journal as durable control-plane history and the state snapshot as derived output

## Constraints

- The assistant repo contains no research data.
- All run artifacts are written into the job repo.
- Final outputs may not contain uncited factual claims.
- Facts and inference must remain distinguishable where possible.
- Disagreements must be preserved until the judge stage.
- Workflow provenance and external evidence are different and must not be conflated.
- Stage references such as `research-a`, `judge`, or critique artifact IDs do not satisfy evidence-citation requirements.
- Research, critique, and judge stages must pass structured source-aware validation before the workflow may continue downstream.

## Planned Hardening

The intended next hardening steps are:

1. strengthen adapter qualification beyond the current fixture probes so provider drift is caught before live workflow failures
2. strengthen source-registry governance beyond source classes and simple ID resolution
3. unify publication around the same normalized contract model as the core execution stages
4. tighten intake and stage schemas further where live runs expose underconstrained fields
5. extend the new structured semantic support model into remaining markdown compatibility and publication edges until marker-only classification is no longer on the critical path
