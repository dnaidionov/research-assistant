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
- not yet fully implemented in `scripts/extract_claims.py`

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
- current implementation still uses only `fact` and `inference`

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
- target architecture only; `run_workflow.py` does not scaffold sidecars yet

---

## Decision 11: The workflow runner must evolve from scaffold to gatekeeper

Reason:
- deterministic file creation is useful but not enough for trust
- placeholder artifacts, missing sidecars, and uncited facts should block progression once the contracts exist

Decision:
- quality gates are part of the intended orchestration design
- until those gates exist, the system should be described as an auditable scaffold rather than a reliable evidence adjudication engine
