# Architecture Decisions

## Decision 1: Separate repos per job

Reason:
- privacy isolation
- independent sharing
- audit integrity

Rejected:
- single monorepo

---

## Decision 2: Assistant repo contains no research data

Reason:
- safe to share publicly
- no accidental leaks

---

## Decision 3: Jobs linked via metadata, not submodules

Reason:
- simplicity
- avoids git complexity

Rejected:
- submodules
- symlinks as primary mechanism


---

## Decision 4: Local filesystem as source of truth

Reason:
- tool independence
- portability

---

## Decision 5: Obsidian as optional layer

Reason:
- navigation and synthesis only
- not canonical storage

---

## Decision 6: Claim-level audit required

Reason:
- reduces hallucination risk
- enforces traceability

## Decision 7: Codex as execution layer

Reason:
- supports multi-step workflows
- persistent state
- code evolution

---

## Decision 8: Separate provenance from evidence

Reason:
- internal workflow artifacts show who asserted or preserved a claim
- external sources are the actual evidence for domain claims
- conflating the two creates false confidence in the claim register

Status:
- architectural decision accepted
- partially implemented in `scripts/extract_claims.py` and the structured-stage runner path
- the workflow now enforces source-ID resolution through a run-level registry for structured research and judge outputs
- structured research, critique, and judge artifacts may now declare typed `support_links`, and the claim-map builder derives evidence versus provenance from those typed links plus source classes
- local reasoning dependencies are now modeled separately as `claim_dependencies` so local claim IDs are not misused as source identifiers
- `job_input` sources remain admissible evidence when they directly state current-system facts, requirements, or constraints under analysis; they are not limited to provenance-only use
- `context` links are no longer treated as sufficient semantic support for world claims in structured fact and inference validation; those claims now require at least one world-supporting `evidence` link
- prompt contracts and source-registry merging now both prefer exact source locators over degraded site-root or bare-domain references, so locator fidelity is treated as part of the evidence contract rather than a stylistic preference
- markdown-only extraction and compatibility paths still rely on marker parsing, so the decision is implemented end to end only on the structured path, not yet across every fallback path
- the runner now states the evidence rule explicitly in stage prompts and validation errors: evidence is never implicit, and nearby citations do not satisfy support requirements for a new item

---

## Decision 9: Claim register needs more than fact vs inference

Reason:
- adjudication produces evaluations, open questions, evidence gaps, and structure notes that are useful but are not truth claims
- forcing all extracted items into `fact` or `inference` dilutes the register and makes validation noisy

Accepted target classes:
- fact
- inference
- evaluation
- decision
- recommendation
- assumption
- open_question
- evidence_gap
- artifact_reference
- report_structure

Status:
- current implementation now recognizes additional classes such as `evaluation`, `decision`, `recommendation`, `assumption`, `open_question`, `evidence_gap`, `artifact_reference`, and `report_structure`
- downstream validation still treats only a subset of those classes as first-class gate targets
- specifically, `fact`, `inference`, `decision`, and `recommendation` are currently truth-gated, while `evaluation` remains non-gating because the repo still uses it for confidence summaries, disagreement framing, and other adjudication text that is not always a world claim

---

## Decision 10: Markdown alone is insufficient for stage contracts

Reason:
- downstream extraction from freeform markdown is too brittle
- critique and judge stages need structured machine-readable inputs
- hard gates require explicit structured fields rather than text heuristics

Decision:
- each execution stage should eventually emit markdown plus a structured JSON sidecar
- the JSON sidecar should minimally carry key claims, evidence sources, assumptions, uncertainties, and unresolved questions

Status:
- materially implemented
- `run_workflow.py` now scaffolds authoritative JSON outputs for intake, research, critique, and judge stages, plus a run-level `sources.json`
- `execute_workflow.py` now executes intake through internal source declaration / fact-lineage / normalization / merge substeps and executes research, critique, and judge through an internal source-pass / claim-pass / deterministic-markdown pipeline, validates the combined structured artifact through a shared stage-validation path, and uses that structured result as the canonical gate
- that decomposition is now strict rather than cosmetic: source-pass and claim-pass have separate validators, source-pass may emit only `stage` and `sources`, and claim-pass must omit `sources`
- intake now validates source-backed `known_facts` with short supporting excerpts and stable source anchors, contributes its declared `job_input` sources into the run-level source registry before research begins, and keeps direct facts separated from working inferences through decomposed intake substeps
- when structured JSON is valid but the paired markdown artifact is weaker than the markdown contract, the runner now regenerates markdown from the structured artifact so downstream markdown-only stages consume a normalized bridge representation
- structured substeps now write only to scratch markdown paths under `audit/substeps/`; final `stage-outputs/*.md` remains runner-owned and is written only after stage validation succeeds
- markdown-to-JSON synthesis has been removed for structured stages, and the runner no longer parses authoritative artifacts out of stdout. Adapter executors now own deterministic artifact materialization instead. Markdown compatibility still exists as ingestion, but it is no longer a separate truth model.

---

## Decision 11: The workflow runner must evolve from scaffold to gatekeeper

Reason:
- deterministic file creation is useful but not enough for trust
- placeholder artifacts, missing sidecars, and uncited facts should block progression once the contracts exist

Decision:
- quality gates are part of the intended orchestration design
- until those gates exist, the system should be described as an auditable scaffold rather than a reliable evidence adjudication engine

Status:
- partially implemented
- `execute_workflow.py` now applies source-aware structured gates for research, critique, and judge stages through one shared stage-validation module
- repo-level final-artifact readiness and the final artifact generator now share one publication-validation path for uncited facts, uncited inferences, provenance-only support, and unclassified markers
- that shared publication path now also resolves referenced source IDs against structured judge sources when they are available, so readiness and publication use the same unresolved-reference rules
- canonical claim-register summary logic is now shared across structured stage sidecar generation, standalone markdown extraction, readiness checks, and final publication
- intake now has an explicit runtime contract validator, and source records now normalize into explicit source classes for publication policy
- source normalization now also emits first-pass policy metadata and outcomes, so a source may be syntactically valid but still blocked or disfavored by publication policy
- the system is still not a trustworthy evidence adjudication engine because source governance is still shallow beyond source classes, provider compliance can still drift after qualification, and provenance-versus-evidence handling still relies on marker parsing outside the structured path
- the canonical claim-register substrate now distinguishes truth-gated claim classes from non-gating adjudication classes and flags unsupported recommendations separately from uncited facts or inferences
- the runner now applies one bounded repair attempt for structured stages that fail validation narrowly and cancels sibling subprocesses after the first fatal failure in a parallel stage group, which reduces wasted token burn without pretending the full planned multi-step stage pipeline is already implemented
- that bounded repair path now excludes missing-artifact and unreadable-JSON failures, and decomposed structured stages now resume at substep granularity instead of always restarting from source-pass
- the runner now also pre-qualifies configured adapters and requires explicit provider trust for intake and structured stages, using multiple stage-like probes instead of one generic smoke test. Trust is now layered as `structured_safe_smoke`, `structured_safe_regression`, and `structured_safe_realistic`; jobs may require stronger tiers globally or per stage. The `workflow-regression` profile uses sanitized real prompt-packet content rather than only toy prompt strings, its critique/judge probes are part of the structured-safe decision rather than informational extras, and the `workflow-regression-realistic` profile now uses frozen sanitized fixture families from the repo. Those families are now explicit and extensible, with `neutral` as the default baseline and domain-shaped families such as `hardware-tradeoff` and `policy-analysis` as opt-in extensions. `scripts/create_fixture_family.py` now scaffolds new families from the neutral baseline so extension stays standardized. A separate `scripts/run_live_drift_check.py` path now exists to run the full workflow against a stable reference-job family outside normal execution. This closes the old runner-side stdout-recovery seam but does not eliminate provider drift as an operational risk
- workflow state is now backed by append-only `events.jsonl` journals, `workflow-state.json` is treated as a derived snapshot, and `scripts/rebuild_workflow_state.py` can reconstruct the snapshot from the event log after interruption. This materially improves crash recovery and auditability without introducing a database, but it is still not a fully transactional artifact system.
- live snapshot updates inside parallel stage groups are now serialized through a shared state lock in the runner, so `research-a`/`research-b` and critique siblings no longer mutate the same in-memory state object and `workflow-state.json` concurrently. The event journal remains the durable source of truth, but the snapshot path is no longer left to race opportunistically.
- provider runtime scorecards now persist qualification history, stage outcomes, repair attempts, live-drift outcomes, and quarantine state per configured provider. Jobs may declare `workflow.execution.provider_runtime_policy` to quarantine providers after repeated failures or live-drift regressions and reroute specific stages through configured fallbacks. `scripts/provider_scorecards_report.py` summarizes those scorecards for operators.
- live-drift accounting is now tied to providers actually observed in the drift run, using run-scoped qualification/stage history rather than every provider declared in the job catalog. Unused fallbacks and dormant providers no longer accumulate synthetic drift failures simply because they exist in `config.yaml`.
- event replay now restores `*_started` journal events as in-memory `running` state during rebuild, so a missing snapshot cannot silently downgrade active work to `started` and then to `scaffolded`.
- provider scorecards now count only fresh execution outcomes. Re-entering a completed run no longer appends synthetic `completed` stage results or inflates provider totals during resume.
- provider scorecards now also separate adapter execution outcomes from downstream claim-extraction failures. A stage that executed successfully but later failed claim extraction is recorded once as adapter `completed`; the later extraction failure still fails the run, but it does not create a second synthetic provider `failed` event for the same attempt.
- a structured-stage repair that exits `0` but still fails to materialize its required JSON artifact is now treated as a hard missing-artifact failure, not as an implicit cancellation. That keeps the authoritative artifact contract consistent: missing structured output is not a recoverable success path.
- research quality now has explicit benchmarked gates. `quality_policy` participates in final-artifact readiness/publication checks, and `scripts/run_quality_benchmarks.py` evaluates stable benchmark fixtures under `fixtures/benchmarks/families/` for one-sided source selection, disfavored recommendation support, missing required comparison dimensions, evidence-quality mismatch, and disagreement collapse.
- judge synthesis may now carry optional `brief_improvements` for requester-actionable missing inputs. The markdown bridge round-trips that section back into structured JSON, and final artifact generation inserts it after confidence and before references so the optional section does not reorder the required artifact contract.

---

## Decision 12: Do not transition to a full agentic workflow before contract hardening

Reason:
- the current system's primary failures are contract mismatches, bridge failures, and fragmented validation semantics
- adding a hub-and-spoke agent runtime before critique structure, validation unification, and source-governance hardening would multiply failure surfaces rather than simplify them
- the right role for agentic orchestration is after the system has one authoritative machine-readable contract and a clearer control-plane boundary

Alternatives considered:
- Plan 1: contract-first hardening of stage schemas, validation, source handling, publication, and workflow state
- Plan 2: staged transition to a hub-and-spoke orchestrator with bounded worker agents for intake, research, critique, and judge

Decision:
- Plan 1 is the recommended immediate direction
- Plan 2 remains a credible future architecture, but it should follow the high-priority Plan 1 prerequisites rather than replace them

Status:
- accepted as current roadmap guidance
- not yet implemented

---

## Decision 13: Provider and model selection belong in job-level execution config

Reason:
- execution routing should be a job concern, not a runner-code edit
- stage-level provider choice and model pinning need to be auditable in the job repo
- the old primary-secondary CLI split was too coarse once different stages needed different providers

Decision:
- `config.yaml` may define named providers under `workflow.execution.providers`
- each provider declares an `adapter` and may declare a `model` if that adapter supports explicit model selection
- `workflow.execution.stage_providers` maps each execution stage to one named provider
- CLI `--primary-adapter` and `--secondary-adapter` remain fallback compatibility settings when no job-level execution config is present

Status:
- implemented in `scripts/execute_workflow.py`
- Claude is now a supported adapter in the execution runner
- adapter capability remains intentionally explicit: a configured model override is rejected for adapters that cannot honor it
