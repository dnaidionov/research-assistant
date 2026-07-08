# Agentic Workflow Redesign

## Status and Purpose

This document is the concrete design for evolving the research pipeline into an agentic workflow built on skills, subagents, and hook-enforced gates. It is the successor to "Plan 2: Hub-and-Spoke Agentic Workflow" in `redesign-proposal.md`, updated for the July 2026 provider landscape.

Nothing in this document is implemented yet. It is intended as the input to an implementation goal, with phased acceptance criteria at the end.

## Preconditions: Why Now

The redesign proposal recommended deferring agentic orchestration until the contract-first hardening (Plan 1) landed. That precondition is now largely met:

- structured stage JSON is the authoritative machine-readable contract
- stage validation is unified in a shared module (`_stage_validation.py`, `_stage_contracts.py`)
- publication gating is shared between readiness validation and artifact generation
- markdown-to-JSON synthesis is gone; missing structured output is a hard failure

Separately, the provider landscape changed: Gemini CLI stopped serving individual subscriptions on 2026-06-18, and a new generation of subscription-authenticated agentic CLIs replaced the first wave. The adapter layer needs a refresh regardless; this design folds that refresh into the redesign rather than doing it twice.

## Guiding Principle: Two Planes

The current codebase interleaves two different systems:

- a **reasoning plane**: prompt packet assembly, adapter invocation, stdout recovery, retry/repair choreography — the part that fights LLM non-determinism
- a **control plane**: schemas, stage contracts, citation validation, claim gating, source policy, publication guards, workflow state, telemetry, audit — the part that makes outputs trustworthy

The redesign replaces the reasoning plane with agentic execution and keeps the control plane deterministic and code-owned. The boundary rule:

> Guardrails expressed in prompts are suggestions; guardrails in code are guarantees. No gating decision, state transition, publication step, or provenance record may be delegated to an agent.

The job repo filesystem remains the system of record. Because every stage already communicates through validated files, agents and legacy scripts interoperate stage-by-stage — migration never requires a big-bang cutover.

## Provider Landscape (July 2026) and Multi-LLM Strategy

Verified as of 2026-07-02. All primary adapters can authenticate against existing consumer subscriptions rather than metered API keys.

| Adapter | Vendor | Auth (subscription) | Model families | Headless interface |
|---|---|---|---|---|
| `codex` | OpenAI | ChatGPT plan via `codex login` (device-auth for headless) | GPT-5.x / Codex | `codex exec --full-auto` |
| `claude` | Anthropic | Claude plan | Claude | `claude -p --output-format text` |
| `agy` (Antigravity CLI) | Google | Google AI Pro / Ultra | Gemini 3.x | `agy -p` with `--headless` + `--approve` policy, `--output json` |
| `copilot` | GitHub | Copilot plan | multi-vendor: Claude, GPT-Codex; Gemini availability in flux | `copilot -p --allow-all-tools` |

Notes and caveats:

- **Antigravity CLI replaces Gemini CLI.** Gemini CLI still works only with paid Gemini API keys, which violates the subscription-first preference. Antigravity CLI is a closed-source Go binary (`agy`), not the open-source Gemini CLI codebase. Known quirk: it emits no output when stdout is not a TTY; the adapter must wrap invocation (e.g. `script -qec '...' /dev/null`) or rely on `--output json` file targets. The existing `antigravity` adapter in `_cli_adapters.py` targets an `antigravity chat --mode agent` command shape that predates the shipped binary and must be re-verified during qualification.
- **Copilot CLI is a diversity multiplier, not a provider.** One GitHub subscription exposes models from multiple vendors. For provenance, a stage run through Copilot counts as the model family it executed (e.g. `copilot`/`gpt-5.3-codex` is the GPT family), never as a "copilot" family. Copilot's model roster churns (Gemini was reportedly dropped in May 2026), so qualification must pin exact model ids.
- **Goose (Block / Linux Foundation)** is an open-source meta-adapter that can ride existing Claude, ChatGPT, and Gemini subscriptions via the Agent Client Protocol (ACP). It adds a harness layer without adding a model family, so it is a fallback/optionality play, not a core adapter. Revisit if a direct CLI becomes unusable.
- **OpenRouter is an API gateway, not a subscription, and is deliberately out of the default path.** It remains pay-per-token (prepaid credits plus a ~5.5% purchase fee; no monthly plan), so it conflicts with the subscription-first rule. It is still accounted for, in three narrow roles: (1) the only practical route to model families beyond OpenAI/Anthropic/Google — Grok, DeepSeek, Qwen, Kimi, Mistral — if a run wants a third or fourth genuinely independent family; (2) failover when a subscription CLI decays (as Gemini CLI did), since `codex`, opencode, and goose can all point at it as a model provider without new adapter code; (3) its free-model tier for cheap mechanical steps where quality gates carry the risk. OpenRouter routes through existing harnesses rather than being an adapter itself; the provider registry records it as `auth_mode: api-gateway`, which triggers the same cost warning as API keys, and provenance records the underlying model family, never "openrouter".

Policy decisions this landscape implies:

1. **Independence is measured in model families, not CLI binaries.** The execution config guard must reject a run where `research-a` and `research-b` (or the two critique stages) resolve to the same model family, regardless of which adapter delivered them.
2. **Subscription-first authentication.** Adapter qualification records auth mode (`subscription`, `api-key`, or `api-gateway`). Metered modes are permitted but surfaced as a cost warning in telemetry and scorecards.
3. **Provider registry becomes first-class.** Named providers in `config.yaml` gain explicit `model_family` and `auth_mode` fields, resolved and verified at qualification time instead of being implied by adapter name.

## Architecture

### Deterministic control plane (the hub) — kept, extracted

All existing gates survive verbatim in semantics; what changes is packaging. Extract them into a gate-runner library with a CLI and structured JSON results so both the legacy runner and agentic execution consume the same gates:

- contract validation: stage files exist, JSON parses, schema matches stage type
- citation validation: evidence links resolve through `sources.json`, world-claim rules, provenance vs evidence separation
- claim gating: extraction, register integrity, quality-policy gates
- source policy: preferred / allowed-with-caution / disallowed escalation
- publication guard: fail-closed final artifact and final report, rejected drafts preserved
- run integrity: brief-drift refusal, execution-config snapshot guard, workflow state transitions, resume semantics
- telemetry and audit: usage records, configured-vs-actual execution records

A validation failure returns a machine-readable error object (stage, rule id, offending item ids, message) — this is what makes agentic repair loops precise instead of full re-prompts.

### Agentic reasoning plane (the spokes)

One skill per stage: `intake`, `research`, `critique`, `judge`, `final-report`. A skill bundles:

- the stage prompt contract (today's `shared/prompts/*.md` templates)
- the output contract: target paths plus schema id for both `.md` and `.json` outputs
- iteration guidance: self-validate against the schema and the citation rules before emitting; how to consume a gate error object and repair

Skills are the single source of prompt truth with two delivery modes:

- **Claude-side stages** run as subagents (Agent SDK), with the skill loaded natively and gates enforced by hooks
- **External-CLI stages** get the same skill content rendered into a prompt packet and executed through the adapter, with gates enforced by the runner after adapter exit

This preserves multi-LLM independence: research passes and critique pairs keep running on different model families, exactly as today, while gaining in-stage iteration (a research agent that notices its own evidence gap can go fill it before emitting — the gates only care that the artifact validates).

### Orchestrator

- A **declarative workflow definition** (YAML in the assistant repo) describes stages, dependencies, parallel groups, provider bindings, and gate bindings. The current hardcoded 2-pass shape becomes one instance of it.
- A **thin deterministic runner** owns state transitions, resume, parallel dispatch, gate enforcement, and publication. It replaces the imperative orchestration loop in `execute_workflow.py` (~3,200 lines) with a state machine over the workflow definition.
- An **optional orchestrator agent** may sit on top for adaptive behavior (e.g. requesting a supplementary research pass when the judge flags evidence gaps). It can only *request* transitions; the runner validates every request against the workflow definition and gates. If the orchestrator agent is disabled, the runner executes the static definition — full parity with today.

### Gate enforcement points

- Claude-side stages: `Stop` / `PostToolUse` hooks run the gate CLI and block completion on failure, so an agent cannot skip validation
- external-CLI stages: the runner invokes gates after the adapter exits; on failure it feeds the structured error back for a bounded repair loop (one repair attempt per stage by default, configurable)
- publication: runner-owned only; never reachable from inside a stage agent

## Guardrail Preservation Matrix

| Existing guardrail | Home in new design |
|---|---|
| Stage JSON schemas (`schemas/`) | unchanged; referenced by skills and gate runner |
| Citation / evidence-vs-provenance rules | gate runner (from `_stage_validation.py` / `_stage_contracts.py`) |
| Claim register + quality-policy gates | gate runner (from `_research_quality.py`, `extract_claims.py`) |
| Source policy escalation | gate runner; unchanged semantics |
| Disagreement preservation | schema + judge gate; unchanged |
| Publication fail-closed (artifact + report) | runner-owned publication step (from `_publication.py`, `generate_final_report.py`) |
| Brief-drift refusal, config snapshot guard | runner (from `_execution_guards.py`) |
| Configured-vs-actual provider recording | runner + adapter layer, extended with `model_family` and `auth_mode` |
| Usage telemetry | runner + hooks (from `_usage_telemetry.py`), extended with per-agent iteration counts |
| Adapter qualification (`qualify_adapters.py`) | extended to `agy` and `copilot`; adds auth-mode and model-id pinning checks |
| Live drift checks, quality benchmarks, fixture families | unchanged; promoted to migration A/B harness (below) |
| Source link + excerpt verification, entailment spot-checks | unchanged post-run audits |

## Audit and Provenance Additions

Agentic stages do internal tool calls that today's audit trail has no slot for. Additions:

- store full stage-agent transcripts under `runs/<run-id>/audit/agent-transcripts/<stage>.jsonl`
- record per stage: harness (`direct-cli` | `subagent` | `copilot` | `goose-acp`), model family, exact model id, auth mode, iteration/repair count
- gate results (pass/fail + error objects) journaled per attempt, not just final state

## Evals and Migration Verification

The existing eval machinery operates on artifacts, not on the runner, so it survives verbatim and becomes the safety net for the migration itself:

- **A/B harness**: run the same fixture job through the legacy runner and the agentic path; diff gate outcomes, claim registers, provider scorecards, and cost. A migration phase only completes when the diff is explainable and quality is equal or better.
- **Adapter qualification** must pass for any new adapter (`agy`, `copilot`) before a real job may route stages to it, including a non-TTY invocation test (the `agy` stdout quirk makes this mandatory, and it would have caught the original Gemini CLI decay earlier).
- **Benchmarks and drift checks** run per phase as regression gates.

## Migration Plan

### Phase 0 — Gate extraction (no behavior change)

Extract validators, claim gating, publication, and guards into the gate-runner library with JSON results; legacy `execute_workflow.py` consumes it.

Acceptance: zero diff on fixture families and the reference job; all existing tests pass.

### Phase 1 — Adapter refresh and provider registry

Re-verify the `agy` command shape against the shipped binary (including the non-TTY workaround), add the `copilot` adapter, add `model_family` / `auth_mode` to the provider registry, add the model-family independence guard, extend qualification.

Two low-cost pieces of the dynamic-selection future phase (see below) are pulled forward into this phase because the plumbing already exists:

- **Static fallback chains**: a stage provider binding may declare an ordered `fallback` list of named providers. On hard adapter failure (non-zero exit, timeout, quota/rate-limit error, qualification failure at run start) the runner tries the next entry. Each fallback event is journaled through the existing configured-vs-actual execution record, and the model-family independence guard is re-evaluated against the *actual* assignment — a fallback that would collapse research passes onto one family fails the run instead of silently degrading it.
- **Registry metadata stubs**: the provider registry schema reserves optional `cost_tier`, `speed_tier`, and `quota_notes` fields. Schema-only in this phase; no selection behavior reads them yet.

Acceptance: qualification green for `codex`, `claude`, `agy` (and `copilot` if a subscription is available); a config routing both research passes to one model family is rejected; a forced adapter failure on a fixture run falls back to the next chain entry with a journaled event, and a fallback violating family independence aborts the run.

### Phase 2 — One agentic spoke

Run `research-a` as an Agent SDK subagent with hook-enforced gates and transcript audit, everything else legacy.

Acceptance: A/B harness shows equal-or-better benchmark quality, identical gate outcomes on fixtures, cost and iteration counts recorded in telemetry.

### Phase 3 — All spokes skill-driven

All stages execute from skills (subagent or adapter delivery per provider binding); prompt packets are rendered from skills, making `shared/prompts/` the single source of truth; bounded repair loops replace legacy retry choreography.

Acceptance: full-run parity on the reference job across at least two model families; rejected-draft and resume semantics unchanged.

### Phase 4 — Replace the hub

Introduce the declarative workflow definition and thin runner; retire the imperative orchestration loop, packet plumbing, and stdout artifact recovery; optionally enable the orchestrator agent behind a config flag, default off.

Acceptance: resume, drift guards, publication, and telemetry behave identically on the A/B harness; `execute_workflow.py` reduced to a compatibility shim or removed; stdout recovery deleted.

## Future Phase: Dynamic Model Selection and Automatic Fallback

Out of scope for the current redesign (Phases 0–4), except for the two low-cost pieces pulled into Phase 1 above. Recorded here so the current phases don't design against it.

### Dynamic model selection

The job config gains a selection policy that the framework resolves into concrete stage-provider assignments, instead of the operator hand-pinning every stage:

```yaml
workflow:
  execution:
    selection_policy:
      optimize_for: quality        # quality | cost | speed | balanced, or per-stage overrides
      cost_limit:
        per_run: 5.00              # metered-spend ceiling; subscription usage counts as 0 but consumes quota
        per_stage: 2.00
      deadline_minutes: 90         # optional; biases toward faster models/adapters
      stakes: high                 # high pins resolved models for reproducibility; exploratory allows broader routing
```

Inputs the selector draws on, all of which exist or are introduced in Phases 0–4:

- **provider scorecards** — historical per-stage, per-model gate outcomes and quality metrics (`provider_scorecards_report.py`), so routing favors models that actually pass contracts on that stage type
- **adapter qualification state** — trust level, auth mode, pinned model ids
- **registry metadata** — `cost_tier`, `speed_tier`, `model_family`, `quota_notes`
- **stage payload characteristics** — evidence bundle size vs context window, whether the stage needs live web access
- **subscription quota state** — prefer subscription capacity while it lasts; route overflow to metered providers only within `cost_limit`, with the standard cost warning

Use cases beyond the obvious price/quality/speed knobs:

- **budget-capped exploratory runs**: cheap families for both research passes, quality family reserved for the judge
- **quality-max decision memos**: strongest available model per family for research and judge, cost secondary
- **deadline mode**: parallel-friendly fast models, judge kept strong
- **mechanical-substep routing**: claim-pass/source-pass substeps and repair loops to cheap or free-tier models, since the gates carry the correctness risk
- **quota-aware month-end behavior**: as subscription quotas near exhaustion, degrade mechanical stages first, protect judge and final report
- **scorecard-driven continuous improvement**: periodically re-rank families per stage type from accumulated gate outcomes, so the system learns which family critiques best, which judges best
- **degraded mode**: when only one family is reachable, run single-family with an explicit, journaled independence waiver instead of failing — only if the operator opted in

Two hard rules keep this compatible with the control plane:

1. **The selector is deterministic code over declared metadata and recorded metrics.** An agent may *recommend* a policy at intake (e.g. inferring stakes from the brief), but resolution to concrete assignments is a pure function, reproducible from inputs.
2. **Resolution happens at scaffold time into the execution-config snapshot.** A run's provenance shows exactly which models were chosen and *why* (the selector journals its rationale: inputs, ranking, rejected candidates). Runtime deviation from the snapshot happens only through journaled fallback events. The model-family independence guard and all quality gates apply to the resolved plan, not the policy.

### Automatic fallback (full version)

Extends the Phase 1 static chains with richer triggers and policy:

- **triggers**: adapter hard failure, hang/timeout (the `agy` non-TTY class), quota or rate-limit exhaustion, qualification drift detected at run start, and *contract incapability* — a stage that fails the same gate N times gets rerouted to the next provider instead of burning repair attempts
- **policy**: bounded, ordered, family-aware; a metered gateway (OpenRouter) is allowed as terminal fallback with the cost warning; a fallback can never collapse family independence or bypass a gate
- **audit**: every event records trigger, from/to assignment, attempt counts, and gate outcomes before/after, in the execution-config actual record

### Risks specific to this phase

- **reproducibility erosion** — mitigated by scaffold-time resolution and journaled deviations; `stakes: high` disables dynamic routing entirely
- **scorecard overfitting** — selection metrics come from gate outcomes, which models could satisfy minimally; keep benchmarks and entailment spot-checks as the independent check
- **opaque subscription quotas** — plans don't expose spend or remaining quota reliably, so quota-aware routing is heuristic; treat quota state as advisory, cost limits as hard only for metered modes
- **control-plane complexity creep** — the selector must stay a leaf library the runner calls, never a decision-maker inside gates

## Risks

- **Boundary erosion**: the design fails if gating or state logic leaks into prompts. Mitigation: gates callable only from runner/hooks; publication unreachable from agents; review checklist per phase.
- **Cost and variance**: iterative agents are more expensive and less predictable than one-shot passes. Mitigation: iteration caps per stage, telemetry-first rollout, subscription auth by default.
- **Copilot roster churn**: model availability changes under one subscription. Mitigation: qualification pins model ids; scorecards track per-model, not per-adapter.
- **Closed-source `agy`**: behavior can change without notice and the non-TTY quirk may regress. Mitigation: qualification runs through a non-TTY harness; keep `codex`/`claude` capable of covering all stages.
- **Schema evolution across two delivery modes**: skills and packets must stay in lockstep. Mitigation: packets are rendered from skills, never hand-maintained.

## Non-Goals

Unchanged from the redesign proposal:

- replacing the local filesystem as the system of record
- collapsing the multi-stage workflow into one pass
- binding the orchestration layer to one provider, model family, or agent runtime
