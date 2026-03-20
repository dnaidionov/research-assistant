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
Atomic claim register generation with stable IDs, citations, and confidence capture where explicitly stated.

### Phase 8: Artifact Writing
Final job artifact generation from the judged synthesis and claim register.

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

## Constraints

- no uncited claims in final outputs
- sources must be evaluated
- uncertainty must be explicit
- disagreement must be preserved
- assistant repo contains no research data

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
