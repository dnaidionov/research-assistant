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
- the deeper provenance-versus-evidence distinction still relies on marker parsing rather than source-aware semantic adjudication

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
- open_question
- evidence_gap
- artifact_reference
- report_structure

Status:
- current implementation now recognizes additional classes such as `evaluation`, `decision`, `open_question`, `evidence_gap`, `artifact_reference`, and `report_structure`
- downstream validation still treats only a subset of those classes as first-class gate targets

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
- partially implemented
- `run_workflow.py` now scaffolds authoritative JSON outputs for research, critique, and judge stages, plus a run-level `sources.json`
- `execute_workflow.py` validates those structured artifacts through a shared stage-validation path and uses them as the canonical gate for research, critique, and judge stages
- when structured JSON is valid but the paired markdown artifact is weaker than the markdown contract, the runner now regenerates markdown from the structured artifact so downstream markdown-only stages consume a normalized bridge representation
- markdown-to-JSON synthesis has been removed for structured stages, but stdout-recovery compatibility paths still exist for some adapters, so the design is still not at the target structure-first end state

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
- intake now has an explicit runtime contract validator, and source records now normalize into explicit source classes for publication policy
- the system is still not a trustworthy evidence adjudication engine because source governance is still shallow beyond source classes, stdout adapter compatibility paths still exist, and provenance-versus-evidence handling still relies on marker parsing

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
