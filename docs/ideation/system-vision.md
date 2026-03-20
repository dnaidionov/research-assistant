# System Vision

## Problem

Research using LLMs is:
- non-reproducible
- poorly validated
- lacks source traceability
- vulnerable to hallucinations

## Goal

Create a multi-LLM research system that:
- enforces structured workflows
- validates claims against sources
- uses multiple LLMs as adversarial reviewers
- cross-examines outputs
- produces auditable results

### Core Concept

A panel of LLM roles:

- Intake Agent
- Planner
- Researcher(s)
- Source Auditor
- Adversarial Reviewer(s)
- Judge

## Key Design Principles

- isolation of research jobs
- explicit assumptions
- strict source policies
- claim-level traceability
- adversarial validation
- reproducibility over convenience
- disagreement visibility
- structured outputs

## Non-goals

- full autonomy in v1
- replacing human judgment
- optimizing for speed over correctness

## Future Vision

- API-based orchestration
- automated claim validation
- claim scoring
- model performance benchmarking
- reusable knowledge layer (controlled)