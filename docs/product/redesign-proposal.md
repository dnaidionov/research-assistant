# Redesign Proposal

## Objective

Replace the current prose-first workflow contract with a structure-first workflow contract that preserves research quality while materially improving reliability, citation enforcement, and auditability.

Implementation status:

- Research and judge stages now have a partial structure-first rollout in code.
- Critique stages and some compatibility paths are still prose-first.
- Structured research and judge stages now regenerate canonical markdown from authoritative JSON when the markdown bridge artifact is weaker than contract, but that is still a migration bridge rather than the target design.
- This document remains the forward plan for completing the migration.

## Problem Statement

The current design still depends too much on freeform markdown for critiques and migration fallback paths. That still creates recurring failures in four places:

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
