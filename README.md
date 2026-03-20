# Research Assistant Framework

This repository contains the orchestration framework for structured, multi-LLM research workflows.

## Architecture

The system is split into two layers:
- Assistant = orchestration layer
- Jobs = independent research cases

Jobs are linked via metadata, not embedded

### 1. Assistant (this repo)
- prompts
- schemas
- scripts
- templates
- documentation

Contains **no research data**

### 2. Jobs (separate repos)
Located at:

~/Projects/research-hub/jobs/

Each job:
- is its own Git repository
- contains full research lifecycle artifacts
- can be shared independently

---

## Key Principles

- jobs are fully isolated (one repo per job)
- strict separation between system and data
- this repo contains no research data
- no uncited factual claims
- claim-level traceability
- adversarial validation
- reproducibility over convenience

---

## Structure

- `templates/` — job templates
- `shared/` — reusable prompts, policies, rubrics
- `schemas/` — validation schemas
- `scripts/` — automation utilities
- `jobs-index/` — registry of research jobs (metadata only)
- `docs/` — ideation, product design, decisions
- `dashboards/` — Obsidian-friendly navigation
- `inbox/` - inbox for new ideas

---

## Usage

1. Create a new job from template `scripts/create_job.sh`
2. Register it in `jobs-index/`
3. Run research workflow
4. Store all outputs inside the job repo

---

## Workflow

1. Intake → structured brief
2. Research → multiple independent LLM outputs
3. Critique → cross-examination
4. Judge → resolution and synthesis
5. Output → final report + audit artifacts

---

## Execution Model

- ChatGPT → design & reasoning
- Codex → implementation & execution
- Scripts → orchestration layer
- Jobs → persistent storage

---

## Important

This repo must never contain:
- real research data
- client/project names
- sensitive sources

