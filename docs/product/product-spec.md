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
Adversarial review of pass A.

### Phase 5: Critique of B by A
Adversarial review of pass B.

### Phase 6: Judge Synthesis
Resolution and synthesis while preserving unresolved disagreements and retaining external evidence citations.

### Phase 6.5: Stage Claim Validation
Research and judge markdown artifacts are converted into structured claim sidecars and blocked by section-aware validation when required fact or inference items lack external citations.

### Phase 7: Claim Extraction
Atomic claim register generation with stable IDs and explicit separation between workflow provenance and external evidence where marker classification allows.

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

The current repo implements a v1 workflow scaffold and a v1 markdown claim extractor. It does not yet implement a trustworthy evidence adjudication system.

Implemented today:

- deterministic run scaffolding for intake, two research passes, two reciprocal critiques, and judge synthesis
- automated execution orchestration for the current adapter-driven split, with Codex and Gemini as the default pair
- stdout-recovery wrapping for markdown-producing chat adapters that return artifact content without writing the target file
- explicit stage dependencies and per-stage prompt packets
- placeholder stage outputs, workflow state, and run audit artifacts
- scaffolded claim-sidecar targets for research and judge stages
- per-stage driver logs that capture command execution plus output-artifact status for debugging
- markdown claim extraction with stable IDs
- provenance vs external evidence separation inside the claim register
- lexical claim classification, including evaluation handling for disagreement and confidence sections
- strict failure on uncited extracted facts
- section-aware stage validation for required fact and inference sections before downstream execution continues
- separate downstream final artifact generation with readiness gating
- prompt contracts that explicitly forbid replacing evidence citations with workflow-stage references

Known limitations in the current repo:

- claim extraction is lexical and markdown-structure-driven, not semantic
- the claim model is too coarse for adjudication; `fact` and `inference` are not enough
- `run_workflow.py` scaffolds files but does not yet enforce stage-output schemas or hard quality gates
- downstream trust is limited because freeform markdown is still the primary machine-readable exchange format
- provenance vs evidence separation is still marker-based, not semantic
- the workflow still depends on prompt compliance for canonical citation labels; malformed labels are rejected downstream rather than normalized automatically

## Ranked Shortcomings

The current shortcomings, in priority order, are:

1. Freeform markdown is still the primary machine-readable exchange format.
   This remains the main source of brittleness. Stage validation, claim extraction, stdout recovery, and final artifact generation all depend on parsing prose that was written for humans first and machines second.

2. Structured stage sidecars are still derived artifacts rather than authoritative outputs.
   Sidecars now exist, but they are extracted from markdown after the fact. The system still treats prose as the source of truth and structured data as a reconstruction.

3. Validation semantics are fragmented across the workflow.
   Section-aware stage validation, lexical atomic claim extraction, final-artifact gating, and repo validation are different checks with different failure semantics. That increases operator confusion and maintenance cost.

4. Adapter contracts are weak and partially heuristic.
   The runner is provider-agnostic, but that abstraction is still achieved partly through prompt compliance and stdout recovery heuristics rather than a strong write-to-path contract.

5. Source identity is syntactic, not fully modeled.
   Canonical markers such as `SRC-001` exist, but there is still no enforced source registry guaranteeing that every source ID resolves to a concrete source record with metadata and scope.

6. Provenance-versus-evidence separation is still marker-based.
   The architecture is correct, but the implementation still infers the distinction from token shapes rather than source-aware semantics.

7. Workflow state is file-based and non-transactional.
   `workflow-state.json`, stage outputs, sidecars, and logs can still drift during crashes or partial parallel failures. The design is recoverable, but not atomic.

8. The claim model is richer than before but still not fully integrated into downstream logic.
   The extractor recognizes more classes now, but validation and artifact generation still reason over simplified subsets of the model.

9. The system still depends heavily on prompt compliance.
   Prompt contracts are stricter than before, but malformed citation labels, weak source definitions, and structurally awkward outputs are still possible because prompts are guidance, not enforcement.

10. Documentation status can drift behind implementation.
   This is lower impact than the structural issues above, but it still matters because architectural intent and implemented reality diverge quickly in a repo like this.

## Target Claim Model

The next iteration should separate different claim-like objects instead of forcing everything into a truth register.

Target classes:

- `fact`
- `inference`
- `evaluation`
- `decision`
- `open_question`
- `evidence_gap`
- `artifact_reference`
- `report_structure`

Not all classes belong in the same validation path. In particular, `artifact_reference` and `report_structure` should not be treated as first-class truth claims.

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
  "unclassified_markers": []
}
```

## Planned Hardening Path

Priority order for the next iteration:

1. strengthen claim typing and exclude non-truth classes from truth validation
2. add a post-extraction cleanup filter for headings, paths, outline items, and formatting residue
3. require per-stage structured JSON sidecars in addition to markdown
4. add hard workflow gates for placeholders, missing sidecars, uncited facts, and unresolved template residue
5. upgrade from marker-based provenance/evidence separation to stronger semantic classification only if real workflow failures justify the added complexity

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
