# Redesign Proposal

## Objective

Replace the current prose-first workflow contract with a structure-first workflow contract that preserves research quality while materially improving reliability, citation enforcement, and auditability.

Implementation status:

- Research, critique, and judge stages now have a broader structure-first rollout in code.
- Some compatibility paths are still prose-first or prose-derived.
- Structured research and judge stages now regenerate canonical markdown from authoritative JSON when the markdown bridge artifact is weaker than contract, but that is still a migration bridge rather than the target design.
- Structured critique stages now follow the same pattern, which removes one major markdown-only seam but does not eliminate the bridge architecture itself.
- Judge-side non-core synthesis sections now accept richer object forms in code, which reduces false failures but also reinforces the need for explicit schema-governed stage contracts across every stage.
- Final artifact generation now prefers structured judge JSON when available and renders followable references from structured source records, which is closer to the target architecture than the earlier markdown-only renderer.
- Publication gating is now shared between repo readiness validation and final artifact generation, which removes one concrete cross-layer inconsistency but does not yet solve the broader stage-validation split.
- A shared stage-validation module now centralizes structured JSON checks, markdown-contract backstops, canonical markdown regeneration, and structured claim-map generation for core stages.
- Structured stages no longer synthesize authoritative JSON from markdown, intake now has explicit contract validation, and source records now normalize into explicit source classes.
- This document remains the forward plan for completing the migration.

## Problem Statement

The current design still depends too much on freeform markdown in migration fallback paths and bridge layers. That still creates recurring failures in four places:

- stage validation depends on markdown structure
- claim sidecars are reconstructed after the fact
- adapters are forced into heuristic stdout recovery
- final artifacts inherit ambiguity from earlier prose artifacts

This is the root architectural problem. The redesign should address that directly rather than adding more regexes around the current shape.

## Design Principles

- Keep rich prose for humans, but do not use it as the authoritative operational contract.
- Make structured outputs authoritative for workflow gating.
- Make source identity explicit and reusable across stages.
- Keep provenance and evidence separate in first-class data structures.
- Fail early when contracts are broken.
- Preserve provider-agnostic orchestration, but require stronger adapter contracts.

## Proposed Architecture

### 1. Dual Outputs Per Stage

Each stage should emit both:

- `stage-outputs/<stage>.md`
- `stage-outputs/<stage>.json`

The markdown remains human-readable. The JSON becomes the authoritative machine-readable contract.

### 2. Source Registry Per Run

Each run should maintain a first-class source registry, for example:

- `runs/<run-id>/sources.json`

That registry should define:

- canonical source id
- title
- url or local path
- source type
- source authority
- recency or publication date where relevant
- acquisition provenance

Stages should cite only source IDs present in that registry.

### 3. Structured Stage Schemas

The minimum JSON schema shape by stage should be:

#### Research stage

- `summary`
- `facts`
- `inferences`
- `uncertainties`
- `evidence_gaps`
- `preliminary_disagreements`
- `source_evaluation`

Each fact and inference item should carry:

- `id`
- `text`
- `evidence_sources`
- `confidence` where relevant

#### Critique stage

- `supported_claims`
- `unsupported_claims`
- `weak_source_issues`
- `omissions`
- `overreach`
- `unresolved_disagreements`
- `summary`

#### Judge stage

- `supported_conclusions`
- `synthesis_judgments`
- `unresolved_disagreements`
- `confidence_assessment`
- `evidence_gaps`
- `rationale`
- `recommended_artifact_structure`

### 4. Validation Model

Validation should be unified into three layers:

#### Contract validation

- required files exist
- JSON parses
- schema matches stage type

#### Citation validation

- every `fact` has at least one valid evidence source
- every `inference` has at least one valid evidence source
- every cited source id resolves in `sources.json`
- stage references are never treated as evidence

#### Policy validation

- confidence is present where required
- forbidden placeholders are absent
- no unresolved template residue remains

The runner should block progression on any contract or citation validation failure.

### 5. Adapter Contract Redesign

Adapters should no longer be “prompt in, hope file out.”

Target adapter contract:

- input: prompt packet path, output markdown path, output json path
- success means both outputs were written and validated
- stdout and stderr are logs only, not fallback artifact transport

Stdout recovery should remain only as a temporary compatibility layer during migration.

## Migration Plan

### Phase 1: Add structured schemas and source registry

- add stage JSON schemas under `schemas/`
- add `sources.json` schema
- scaffold `sources.json` and stage JSON targets in `run_workflow.py`

### Phase 2: Make models emit JSON directly

- update prompt templates to require both markdown and JSON outputs
- update adapters to write both files deterministically

### Phase 3: Unify validation

- replace split validation logic with one stage-validation module
- use stage JSON as the canonical gate input
- keep markdown validation only for structural sanity checks

### Phase 4: Simplify claim extraction

- generate final claim registers from structured judge JSON instead of markdown parsing
- retain markdown claim extraction only as a compatibility or auditing tool

### Phase 5: Remove heuristic adapter fallback

- remove stdout artifact recovery once all supported adapters comply with the stronger contract

## Expected Benefits

- fewer false positives from markdown parsing
- stronger citation guarantees
- cleaner adapter abstraction
- more reliable resume and failure semantics
- easier downstream artifact generation
- better basis for future UI or API layers

## Main Risks

- prompt complexity increases
- adapter implementations become more opinionated
- schema evolution must be managed carefully
- migration will temporarily require supporting old and new contracts together

## Recommended Next Implementation Order

1. add `sources.json` and stage JSON scaffolding
2. add stage JSON schemas
3. add a unified validation module
4. update research and judge prompts to emit JSON sidecars directly
5. update adapters to write markdown and JSON deterministically
6. move final artifact generation to structured judge data

## Non-Goals

- replacing the local filesystem as the system of record
- collapsing the multi-stage workflow into one pass
- binding the orchestration layer to one provider or model

## Alternatives Considered

### Plan 1: Contract-First Hardening

This alternative prioritizes architectural closure before changing the execution model.

Core idea:

- make structured stage JSON the only authoritative machine-readable contract
- extend structure-first execution to critique stages
- unify validation, claim mapping, publication, and source handling around normalized structured payloads
- reduce and then remove migration bridges such as stdout recovery, markdown-to-JSON synthesis, and markdown regeneration from structured JSON
- strengthen workflow state transitions, source governance, and publication rules before introducing more autonomy

Why it was considered:

- most recent failures have been contract failures, not lack-of-agent failures
- the current system still has overlapping truth layers: prompt, markdown, structured JSON, claim map, publication, and workflow state
- architectural soundness requires those layers to converge before adding more concurrent decision-making components

Main upside:

- directly addresses the actual causes of `run-016`, `run-018`, and the earlier citation and bridge failures
- reduces non-local bugs by collapsing fragmented validation semantics
- creates a safer base for later evolution into stronger orchestration or agentic execution

Main downside:

- less visually ambitious than a broader agentic redesign
- requires more plumbing and contract cleanup before higher-level workflow changes become visible

### Plan 2: Hub-and-Spoke Agentic Workflow

This alternative introduces a central orchestrator with bounded worker agents for workflow stages.

Core idea:

- orchestrator as the hub, owning dependency scheduling, validation, policy, state, retries, source registry merging, and publication
- stage agents as spokes: intake, research-a, research-b, critique-a-on-b, critique-b-on-a, judge
- parallel execution preserved where the current workflow already benefits from it, especially the research and critique pairs
- evidence extraction and final artifact generation remain deterministic runner-owned steps initially rather than autonomous agents

Why it was considered:

- the workflow is already evolving toward orchestrated stage execution with parallel role assignment
- a hub-and-spoke model would improve separation of reasoning work from control-plane responsibilities
- it is a plausible long-term architecture once contracts are stable

Main upside:

- clearer execution ownership and better long-term extensibility
- cleaner provider diversification and benchmarking by role
- better fit for future API-driven orchestration and specialized worker roles

Main downside:

- does not solve the current contract failures by itself
- if introduced too early, it would multiply failure surfaces across mixed markdown, JSON, and bridge contracts
- would likely produce more non-local bugs until critique structure, validation unification, and source governance are already hardened

## Recommendation

Do not implement Plan 2 immediately.

Recommended sequence:

1. execute the high-priority parts of Plan 1
2. finish structure-first rollout across critiques
3. unify validation, source governance, and publication rules
4. then transition toward the Plan 2 hub-and-spoke orchestrator model

Reasoning:

- current failures are primarily contract and policy failures, not orchestration-shape failures
- critique stages are still markdown-only, so the system still depends on bridge logic for correctness
- validation, extraction, publication, and state transitions are still fragmented across multiple scripts
- introducing more autonomous agents now would increase concurrency and control complexity on top of unstable contracts
- Plan 2 becomes a strong next move only after the core structure-first contract is authoritative across the whole workflow
