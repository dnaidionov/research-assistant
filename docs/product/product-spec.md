# Product Specification

## System Components

### 1. Assistant Framework
- prompts
- schemas
- orchestration logic
- templates
- documentation

### 2. Research Jobs
- isolated repositories
- full lifecycle artifacts
- evidence and audit logs

### 3. Job Index
- metadata only
- no research data

## Workflow

### Phase 1: Intake
Input is normalized into an execution-ready intake record.

### Phase 2: Research Pass A
Independent research report with canonical external citations and fact or inference separation.

### Phase 3: Research Pass B
Second independent research report with the same evidence rules.

### Phase 4: Critique of A by B
Adversarial review of pass A with structured critique output plus a human-readable markdown view.

### Phase 5: Critique of B by A
Adversarial review of pass B with structured critique output plus a human-readable markdown view.

### Phase 6: Judge Synthesis
Resolution and synthesis while preserving unresolved disagreements and retaining external evidence citations.

### Phase 6.5: Structured Stage Validation
Research, critique, and judge stages now produce authoritative structured JSON artifacts alongside markdown. The runner validates those JSON artifacts, resolves cited source IDs through a run-level source registry, and blocks downstream execution when the contract is broken.

### Phase 7: Claim Extraction
Claim-register generation from the structured judge artifact when available, with markdown extraction retained as a compatibility path.

### Phase 8: Artifact Writing
Final job artifact generation from the judged synthesis and claim register, with external references only in the user-facing report.

## Roles

- Intake agent
- Researcher A
- Researcher B
- Critic B reviewing A
- Critic A reviewing B
- Judge
- Claim extractor
- Artifact writer

## Output Requirements

Each job must be able to produce:

- research passes
- critique artifacts
- judge synthesis
- source-aware claim register
- disagreement log
- final report with explicit uncertainty where needed

## Current Implementation Status

The current repo now implements a broader structure-first workflow for research, critique, and judge stages, with markdown compatibility layers still present. It still does not implement a trustworthy evidence adjudication system.

Implemented today:

- deterministic run scaffolding for intake, two research passes, two reciprocal critiques, and judge synthesis
- automated execution orchestration for the current adapter-driven split, with Codex and Gemini as the default pair
- automatic incremental run-id selection in `execute_workflow.py` when `--run-id` is omitted, while preserving explicit run-id support and requiring confirmation before continuing an existing explicitly targeted run
- job-level execution-provider configuration through `workflow.execution.providers` and `workflow.execution.stage_providers`, so a job can assign different adapters and supported model overrides per stage without changing runner code
- explicit stage dependencies and per-stage prompt packets
- placeholder stage outputs, workflow state, and run audit artifacts
- append-only workflow event journals at `runs/<run-id>/events.jsonl`
- scaffolded run-level source registries
- scaffolded structured JSON stage outputs for research A, research B, both critique stages, and judge
- explicit intake-contract validation for the intake JSON stage, now with source-backed `known_facts`, intake-declared sources, short supporting excerpts for each fact, stable source anchors, and decomposed source / fact-lineage / normalization execution before the final intake artifact is accepted
- unified structured-stage validation for research, critique, and judge outputs, including source-ID resolution against the run registry
- flexible validation for non-truth-critical narrative sections such as summaries, uncertainties, and source-evaluation notes
- runner-owned source-registry merging; stage agents may declare sources in stage JSON but the runner treats `sources.json` as read-only during execution
- source records now normalize into explicit source classes such as `external_evidence`, `job_input`, `workflow_provenance`, and `recovered_provisional`
- source normalization now also emits first-pass evidence-policy metadata including `authority_tier`, `evidence_kind`, `freshness_status`, `supports_world_claims`, `supports_process_claims`, `policy_outcome`, and `policy_notes`
- external-evidence locators now follow a resolvable-locator policy rather than a URL-only policy; accepted forms include web URLs, concrete local file paths, and stable attachment-style URIs such as `file://`
- bare-domain locators such as `example.com` are currently tolerated as warnings rather than hard failures, but the preferred locator remains the most specific followable page or file available
- prompt contracts now explicitly require agents to retain the exact locator they actually used rather than collapsing it to a site root or bare domain, and the source registry upgrades degraded locators when a later stage provides a more specific one
- stage prompts and validators now explicitly enforce that evidence is never implicit; every fact and world-claim inference or synthesis item must carry explicit evidence on that exact item, and nearby citations do not satisfy the requirement
- structured research, critique, and judge stages now execute through an internal multi-step pipeline: source pass JSON, claim pass JSON, validator-driven bounded repair, then deterministic markdown rendering from the validated structured payload
- source-pass and claim-pass are now strict contracts rather than soft decomposition hints: source-pass may emit only `stage` plus `sources`, and claim-pass must omit `sources`
- the runner now qualifies each configured provider before execution and persists `structured_safe` / `markdown_only` / `unsupported` reports under `runs/<run-id>/audit/adapter-qualification/`
- qualification is now stronger than a generic smoke test: providers are probed against intake JSON, structured source-pass JSON, structured claim-pass JSON, and markdown materialization prompts before structured execution is allowed
- the qualification system now has two layers:
  - `smoke` for execution preflight
  - `workflow-regression` for stage-like regression checks that also cover critique and judge claim-pass behavior
- the qualification system now also has a frozen-fixture realistic layer:
  - `workflow-regression-realistic` for stronger regression checks against stable sanitized prompt packets kept in the repo
- those realistic prompt packets now live in named fixture families under `fixtures/adapter-qualification/families/`
- `neutral` is the default family; `hardware-tradeoff` and `policy-analysis` are current extensions
- when a research area does not fit any existing family, the system should keep using `neutral` first and add a new family instead of mutating the default baseline
- `scripts/create_fixture_family.py` now scaffolds that new family from the neutral baseline so the extension path is standardized instead of manual
- the stronger regression profile now uses sanitized prompt-packet-derived probes rendered from the real intake, research, critique, and judge templates rather than only toy qualification strings
- regression reports now carry profile, probe-set version, adapter version, and a fingerprint of watched inputs so they can be rerun only when prompts, schemas, scripts, or job config changed
- qualification now reports trust tiers, not just coarse classes:
  - `structured_safe_smoke`
  - `structured_safe_regression`
  - `structured_safe_realistic`
- job execution config may now require stronger trust globally or per stage through `workflow.execution.required_provider_trust` and `workflow.execution.stage_required_provider_trust`
- stable sanitized reference jobs now exist under `fixtures/reference-job/families/`, and `scripts/run_live_drift_check.py` can execute the real workflow against a chosen family to catch provider drift outside ordinary job runs
- provider runtime scorecards now persist qualification history, stage outcomes, repair attempts, live-drift history, and quarantine state under each job's `audit/provider-scorecards/`, and `workflow.execution.provider_runtime_policy` can quarantine providers and reroute specific stages through named fallbacks
- intake and all structured stages now require a `structured_safe` provider classification before execution begins
- Claude is now available as a first-class CLI adapter alongside Codex, Gemini, and Antigravity
- explicit model selection is now configured on named provider entries rather than hardwired to stage roles, but only adapters that actually support explicit model selection may accept a configured model override
- structured research, critique, and judge claims may now carry typed `support_links` so support can be classified semantically as `evidence`, `context`, `challenge`, or `provenance`
- structured claims may now also carry `claim_dependencies` so local fact or claim references are modeled separately from source support instead of being smuggled into `support_links`
- structured claim-map generation now derives `evidence_sources` and `provenance` from typed support links when present instead of relying only on flat marker classification, and preserves `claim_dependencies` for local reasoning traceability
- `job_input` remains admissible evidence for claims about the current system, stated requirements, and explicit constraints when the provided brief directly contains those facts
- `context` links no longer satisfy the semantic evidence requirement for facts or inferences that assert world claims; those claims now require at least one world-supporting `evidence` link
- final publication now fails when any referenced evidence source is unresolved instead of rendering a bare source ID into the user-facing report
- source-quality warnings now flag `job_input` locators that point at prompt packets so the workflow can prefer the underlying canonical artifact such as `brief.md` or `config.yaml`
- source validation now rejects duplicate source IDs within a stage payload and warns when multiple external source IDs point at the same locator
- markdown-only claim extraction can now consult the run-level source registry so provenance-versus-evidence classification follows source classes when a registry is available instead of relying only on marker patterns
- final-artifact readiness checks and final-artifact generation now share the same publication-validation path and structured-reference resolution rules
- `quality_policy` now participates in final-artifact readiness and publication validation, and `scripts/run_quality_benchmarks.py` evaluates stable benchmark fixtures under `fixtures/benchmarks/families/`
- canonical claim-register summaries are now built through one shared substrate, so structured stage sidecars, standalone extraction, readiness checks, and final publication all reason over the same summary fields
- that canonical claim substrate now distinguishes truth-gated claim classes from non-gating adjudication classes and separately flags unsupported recommendations that carry evidence but no explicit rationale or risk accounting
- structured inferences may reference local fact IDs for convenience, but the runner now resolves those references back to canonical external source IDs before validation
- scaffolded claim-sidecar targets for research, critique, and judge stages
- shared structured-stage validation now centralizes source-aware JSON validation, markdown-contract backstops, canonical markdown regeneration, and claim-map generation for structured stages
- when structured JSON passes but the paired markdown artifact is weaker than the stage contract, the runner now rewrites canonical markdown from the authoritative JSON during stage validation rather than delaying that repair until later post-processing
- judge validation now accepts richer non-core synthesis structures such as disagreement objects, topic-based confidence summaries, and object-based recommended artifact outlines, and the bridge layers normalize those shapes for markdown and claim-map consumers
- critique validation now accepts structured section payloads for supported claims, unsupported claims, weak-source issues, omissions, overreach, unresolved disagreements, and critique summaries with confidence
- per-stage driver logs that capture command execution plus output-artifact status for debugging
- structured stages now get one bounded runner-owned repair attempt when the adapter writes artifacts that are close but contract-invalid; the repair pass is fed the exact validator errors and is limited to structural correction rather than fresh research
- missing or unreadable structured substep output is now a hard failure rather than a repair candidate; the bounded repair pass is reserved for structurally close payloads only
- parallel stage groups now cancel sibling subprocesses after the first fatal stage failure and persist `cancelled` stage status instead of letting siblings continue burning time and tokens unnoticed
- decomposed structured stages now use runner-owned scratch markdown paths under `audit/substeps/`; final human-facing markdown is written only after the structured artifact passes validation
- decomposed structured stages now resume at substep granularity when a previously validated source-pass or claim-pass artifact is still usable
- run lifecycle changes are now also written into append-only workflow events, and `workflow-state.json` is rebuilt from that journal rather than treated as the only source of truth
- atomic temp-file replacement now backs `write_text` and `write_json`, so state and artifact writes are no longer direct in-place overwrites
- `scripts/rebuild_workflow_state.py` can reconstruct `workflow-state.json` from `events.jsonl` after interruption or snapshot loss
- markdown claim extraction with stable IDs
- structured claim-register generation from judge JSON in the automated workflow path
- provenance vs external evidence separation inside the claim register, now partly semantic on the structured stage path
- lexical claim classification, including evaluation handling for disagreement and confidence sections
- strict failure on uncited extracted facts
- section-aware markdown validation retained as a migration backstop for required fact, inference, and critique-summary sections
- separate downstream final artifact generation with readiness gating, now preferring structured judge JSON over markdown scraping and rendering followable reference entries rather than bare source IDs
- shared publication validation for claim-register readiness now powers both repo-level final-artifact readiness checks and the final artifact generator itself
- final publication now rejects referenced provisional or workflow-provenance sources when structured source records are available
- prompt contracts that explicitly forbid replacing evidence citations with workflow-stage references
- stage-claim extraction now logs internal failures explicitly instead of failing silently before emitting a driver log
- workflow-state now advances to terminal run-level statuses such as `completed` and `failed` during execution rather than remaining stuck at the scaffold status
- standalone claim extraction can now consume structured stage JSON directly instead of always falling back to lexical markdown parsing

Known limitations in the current repo:

- the claim model is still not rich enough for full adjudication; it now tracks recommendations and assumptions explicitly, but topic-level disagreements and recommendation-risk structures are still shallow
- downstream trust is still limited because markdown compatibility remains a weaker ingestion path and some provider CLIs can still fail by emitting mixed chatter instead of the exact structured artifact requested
- provenance vs evidence separation is now semantic on the structured stage path, but markdown-only extraction and some compatibility paths still rely on marker classification
- the workflow still depends on prompt compliance for exact structured JSON writes from some adapters; runner-side artifact parsing is gone, but provider CLIs can still fail by emitting mixed chatter instead of exact JSON
- the runner now decomposes intake and the structured stages internally, but markdown-only compatibility paths still exist at some downstream edges
- intake now carries source-backed `known_facts` plus an intake-declared `sources` list and per-fact `source_excerpt` and `source_anchor`, which removes the old freeform `source_basis` weakness for direct brief/config facts and gives each intake fact basic auditability

## Ranked Shortcomings

The current shortcomings, in priority order, are:

1. Structured execution is only partially rolled out.
   Research, critique, and judge now have authoritative JSON contracts, and intake is now source-backed and contract-validated, but publication and adapter compatibility paths still sit outside one canonical normalized execution model.

2. Validation semantics are still fragmented across the workflow.
   The claim-register substrate is now shared across structured sidecars, standalone extraction, readiness checks, and final publication, but stage validation, intake validation, and publication/source policy still live in separate modules rather than one fully unified contract engine.

3. Adapter contracts are still weaker than they should be.
   The runner now passes explicit structured-output paths, uses deterministic adapter executors, pre-qualifies adapters before structured execution, and supports stronger regression profiles with stale-aware reruns, sanitized prompt-packet-derived probes, and frozen realistic fixtures. The remaining weakness is provider compliance over time: some CLIs can still drift or degrade on real prompts even after passing compact and realistic regression fixtures.

4. Source identity is now modeled, but source governance is still shallow.
   A run-level `sources.json` exists, source IDs must resolve, and source records now carry basic policy metadata and outcomes, but the system still does not enforce richer freshness thresholds, authority scoring, or topic-level conflict policy.

5. Provenance-versus-evidence separation is only partially semantic.
   Structured stages now support typed support links, explicit claim dependencies, and source-class-aware derivation, but markdown-only extraction and some downstream compatibility paths still infer meaning from token shapes.

6. Workflow state is still file-based.
   The runner now journals lifecycle events and rebuilds `workflow-state.json` from that journal, and state writes are atomic temp-file replacements. The remaining weakness is that the system is still file-based rather than a fully transactional artifact database.

7. The claim model is richer than before but still not fully integrated into downstream logic.
   The extractor and publication path now distinguish truth-gated classes from non-gating adjudication classes and explicitly flag unsupported recommendations, but downstream logic still reasons over simplified subsets of the model and does not yet treat topic-level disagreement as a first-class adjudication object.

8. The system still depends heavily on prompt compliance.
   Prompt contracts are stricter than before, but malformed citation labels, weak source definitions, and structurally awkward outputs are still possible because prompts are guidance, not enforcement.

9. Provider capability symmetry is still incomplete.
   Stage-provider selection is now job-configurable, but adapters do not expose equivalent control surfaces. Gemini and Claude support explicit model flags; Antigravity currently does not, so model configurability remains adapter-dependent.

10. Documentation status can drift behind implementation.
   This is lower impact than the structural issues above, but it still matters because architectural intent and implemented reality diverge quickly in a repo like this.

## Target Claim Model

The next iteration should separate different claim-like objects instead of forcing everything into a truth register.

Target classes:

- `fact`
- `inference`
- `evaluation`
- `decision`
- `recommendation`
- `assumption`
- `open_question`
- `evidence_gap`
- `artifact_reference`
- `report_structure`

Not all classes belong in the same validation path. In particular, `artifact_reference` and `report_structure` should not be treated as first-class truth claims, and `evaluation` remains non-gating in the current implementation because it still carries disagreement framing and confidence summaries that are not always world claims.

## Provenance And Evidence

The system should distinguish:

- provenance: which workflow artifact asserted, preserved, or adjudicated a claim
- evidence: which external sources support a claim about the world

These are different concepts. Internal stage references are useful for audit traceability, but they are not sufficient evidence.
Canonical evidence markers are external source IDs such as `SRC-001`, `DOC-001`, numbered `S123`, or direct URLs. Workflow-stage references are provenance, not evidence.

Target structured shape:

```json
{
  "id": "C001",
  "text": "Example claim text.",
  "type": "fact",
  "provenance": ["PASS-A", "CRIT-B-A"],
  "evidence_sources": ["S001", "S004"],
  "claim_dependencies": ["F-002"],
  "support_links": [
    {"source_id": "S001", "role": "evidence"},
    {"source_id": "DOC-001", "role": "context"},
    {"source_id": "CRIT-B-A", "role": "provenance"}
  ],
  "unclassified_markers": []
}
```

## Planned Hardening Path

Priority order for the next iteration:

1. continue strengthening adapter qualification from the current realistic frozen fixtures toward larger prompt packets and stronger periodic live provider drift checks
2. strengthen source-registry governance beyond source classes and ID resolution
3. unify publication around the same normalized contract model as the core execution stages
4. tighten intake and stage schemas further where live runs expose underconstrained fields
5. extend the new semantic support-link model beyond the structured path so markdown compatibility layers and publication logic no longer fall back to marker-only provenance/evidence classification
6. decide whether intake should eventually emit richer fact-level provenance such as precise machine-readable spans now that source-backed facts, excerpts, and anchors exist

The concrete redesign path that operationalizes those priorities is documented in [redesign-proposal.md](/Users/Dmitry_Naidionov/Projects/research-hub/research-assistant/docs/product/redesign-proposal.md).

## Constraints

- no uncited claims in final outputs
- sources must be evaluated
- uncertainty must be explicit
- disagreement must be preserved
- assistant repo contains no research data
- product documents must distinguish implemented behavior from target architecture

## Execution

- scripts orchestrate the workflow
- prompt packets define stage behavior
- jobs store state and outputs
- provider execution is handled through external CLIs or adapters, not built into the core scaffold runner

## Success Criteria

- reproducible run scaffolding
- traceable claims
- visible disagreements
- auditable workflow state
- clean API integration path later
