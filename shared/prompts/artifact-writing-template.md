# Artifact Writing Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`

## Objective

Write the final user-facing artifact for the job using the judge synthesis and claim register.

## Non-Negotiable Rules

- Do not introduce new factual claims that are absent from the claim register.
- Keep facts and inference distinguishable where practical.
- Preserve a visible disagreement log for unresolved issues.
- Every factual statement in the artifact must remain cited.

## Required Output Sections

1. Final artifact
2. Claim coverage note
3. Disagreement log
4. Open questions

## Source Materials

Use only run artifacts produced earlier in this workflow.
