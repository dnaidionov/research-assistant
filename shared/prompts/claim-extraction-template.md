# Claim Extraction Prompt

Stage ID: `{stage_id}`
Run ID: `{run_id}`
Depends On: `{depends_on}`
Expected Output: `{stage_output_path}`

## Objective

Convert the judge synthesis into an atomic claim register.

## Non-Negotiable Rules

- Each claim must express one atomic proposition.
- Assign stable IDs in output order.
- Capture citations exactly as written.
- Mark each claim as `fact` or `inference`.
- If a fact lacks citation support, flag it instead of silently accepting it.

## Required Output Format

Return JSON with:

- `claims`: ordered list of atomic claims
- `summary`: counts and uncited fact IDs

## Source Materials

Use the judge synthesis output from this run as the primary source.
