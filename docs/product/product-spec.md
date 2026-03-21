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
Independent research report with citations and fact or inference separation.

### Phase 3: Research Pass B
Second independent research report with the same evidence rules.

### Phase 4: Critique of A by B
Adversarial review of pass A.

### Phase 5: Critique of B by A
Adversarial review of pass B.

### Phase 6: Judge Synthesis
Resolution and synthesis while preserving unresolved disagreements.

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
- explicit stage dependencies and per-stage prompt packets
- placeholder stage outputs, workflow state, and run audit artifacts
- markdown claim extraction with stable IDs
- provenance vs external evidence separation inside the claim register
- coarse lexical claim classification
- strict failure on uncited extracted facts
- separate downstream final artifact generation with readiness gating

Known limitations in the current repo:

- claim extraction is lexical and markdown-structure-driven, not semantic
- the claim model is too coarse for adjudication; `fact` and `inference` are not enough
- `run_workflow.py` scaffolds files but does not yet enforce stage-output schemas or hard quality gates
- downstream trust is limited because freeform markdown is still the primary machine-readable exchange format
- provenance vs evidence separation is still marker-based, not semantic

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
2. separate provenance from external evidence in claim artifacts
3. add a post-extraction cleanup filter for headings, paths, outline items, and formatting residue
4. require per-stage structured JSON sidecars in addition to markdown
5. add hard workflow gates for placeholders, missing sidecars, uncited facts, and unresolved template residue

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
- provider execution is external to v1 orchestration

## Success Criteria

- reproducible run scaffolding
- traceable claims
- visible disagreements
- auditable workflow state
- clean API integration path later
