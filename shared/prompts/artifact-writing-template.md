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
- Preserve unresolved disagreement in the comparison or uncertainty sections.
- Every factual statement in the artifact must remain cited.
- The `# References` section must list external evidence sources only.
- Keep workflow provenance in audit artifacts, not in the user-facing references list.

## Required Output Sections

1. `# Executive Summary`
2. `# Options Comparison`
3. `# Recommendation`
4. `# Confidence And Uncertainty`
5. `# References`
6. `# Open Questions`

## Optional Output Sections

- `# Brief Improvement Recommendations`
  - Include this only when the judge record identifies concrete requester-supplied inputs or clarifications that would materially improve the quality, specificity, or decisiveness of the research outcome.
  - When present, render it after `# Confidence And Uncertainty` and before `# References`.

## Source Materials

Use only run artifacts produced earlier in this workflow. Treat workflow provenance as audit material rather than as external support.
