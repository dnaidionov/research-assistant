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

### Phase 6.5: Structured Stage Validation
Research and judge stages now produce authoritative structured JSON artifacts alongside markdown. The runner validates those JSON artifacts, resolves cited source IDs through a run-level source registry, and blocks downstream execution when the contract is broken.

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

The current repo now implements a mixed structure-first workflow for research and judge stages, with markdown compatibility layers still present. It still does not implement a trustworthy evidence adjudication system.

Implemented today:

- deterministic run scaffolding for intake, two research passes, two reciprocal critiques, and judge synthesis
- automated execution orchestration for the current adapter-driven split, with Codex and Gemini as the default pair
- stdout-recovery wrapping for markdown-producing chat adapters that return artifact content without writing the target file
- explicit stage dependencies and per-stage prompt packets
- placeholder stage outputs, workflow state, and run audit artifacts
- scaffolded run-level source registries
- scaffolded structured JSON stage outputs for research A, research B, and judge
- unified structured-stage validation for research and judge outputs, including source-ID resolution against the run registry
- flexible validation for non-truth-critical narrative sections such as summaries, uncertainties, and source-evaluation notes
- runner-owned source-registry merging; stage agents may declare sources in stage JSON but the runner treats `sources.json` as read-only during execution
- scaffolded claim-sidecar targets for research and judge stages
- per-stage driver logs that capture command execution plus output-artifact status for debugging
- markdown claim extraction with stable IDs
- structured claim-register generation from judge JSON in the automated workflow path
- provenance vs external evidence separation inside the claim register
- lexical claim classification, including evaluation handling for disagreement and confidence sections
- strict failure on uncited extracted facts
- section-aware markdown validation retained as a migration backstop for required fact and inference sections
- separate downstream final artifact generation with readiness gating
- prompt contracts that explicitly forbid replacing evidence citations with workflow-stage references

Known limitations in the current repo:

- critique stages still use markdown-only contracts
- claim extraction outside the automated structured path is still lexical and markdown-structure-driven, not semantic
- the claim model is too coarse for adjudication; `fact` and `inference` are not enough
- structured-output enforcement is partial; only research and judge stages are structure-first today
- downstream trust is still limited because critiques and some compatibility paths still rely on markdown as a machine-readable exchange format
- provenance vs evidence separation is still marker-based, not semantic
- the workflow still depends on prompt compliance for canonical citation labels; malformed labels are rejected downstream rather than normalized automatically
- long-running parallel stages can still delay surfaced failure because the runner waits for sibling futures to settle before exiting the stage group

## Ranked Shortcomings

The current shortcomings, in priority order, are:

1. Structured execution is only partially rolled out.
   Research and judge now have authoritative JSON contracts, but critiques are still markdown-only and compatibility fallbacks still synthesize structure from prose when adapters fail to write JSON directly.

2. Validation semantics are still fragmented across the workflow.
   Structured-stage validation is better than before, but markdown validation, lexical extraction, final-artifact gating, and repo validation are still separate mechanisms with different failure semantics.

3. Adapter contracts are still weaker than they should be.
   The runner now passes explicit structured-output paths and a source-registry path, but it still carries migration fallbacks such as markdown recovery and markdown-to-JSON synthesis.

4. Source identity is now modeled, but source governance is still shallow.
   A run-level `sources.json` exists and source IDs must resolve, but the system does not yet enforce richer deduplication, freshness, or authority policies.

5. Provenance-versus-evidence separation is still marker-based.
   The architecture is correct, but the implementation still infers the distinction from token shapes rather than source-aware semantics.

6. Workflow state is file-based and non-transactional.
   `workflow-state.json`, stage outputs, sidecars, and logs can still drift during crashes or partial parallel failures. The design is recoverable, but not atomic.

7. The claim model is richer than before but still not fully integrated into downstream logic.
   The extractor recognizes more classes now, but validation and artifact generation still reason over simplified subsets of the model.

8. The system still depends heavily on prompt compliance.
   Prompt contracts are stricter than before, but malformed citation labels, weak source definitions, and structurally awkward outputs are still possible because prompts are guidance, not enforcement.

9. Documentation status can drift behind implementation.
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

1. extend authoritative structured contracts to critique stages
2. collapse fragmented validation into one shared stage-validation module and one publication gate
3. remove markdown-to-JSON synthesis once adapters comply with deterministic structured writes
4. strengthen source-registry governance beyond simple ID resolution
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
