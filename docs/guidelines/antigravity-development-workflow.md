# Antigravity Development Workflow

This document outlines the strict project guidelines for multi-agent development using Antigravity. It specifically defines the pull request (PR) code review lifecycle and inter-agent handoffs.

## Agent Roles

The development lifecycle involves two primary agent roles to ensure high-quality software delivery and independent verification:

1. **Developer Agent:** Responsible for implementing features, writing code, pushing branches, and opening the Pull Request.
2. **Code Review Agent:** An independent agent invoked specifically to run code reviews against the Developer Agent's PR.

## Core Constraints

### Context Isolation
The **Code Review Agent** must **not** share context with the Developer Agent. This ensures an unbiased, fresh perspective on the proposed changes.
- The Code Review Agent must be spawned with an empty conversation history.
- Before reviewing code, the Code Review Agent must independently read and understand the project documentation (`README.md`, `docs/product/*`, `docs/decisions/*`, etc.) to align itself with the project's architecture and general constraints.

### Review Focus
The primary focus of the Code Review Agent at this stage is **general code quality**. This includes:
- Code correctness and logic.
- Readability and maintainability.
- Potential edge cases or bugs.
- Adherence to language and framework idiomatic practices.

## The Pull Request Lifecycle Protocol

The interaction between the Developer Agent and the Code Review Agent follows a strict sequence of steps tracked via GitHub Pull Requests.

### Step 1: PR Creation & Handoff
1. The **Developer Agent** completes their implementation, pushes the feature branch to the remote repository, and opens a Pull Request in GitHub.
2. The Developer Agent explicitly hands off the workflow to the **Code Review Agent**.

### Step 2: Initial Code Review
1. The **Code Review Agent** analyzes the PR diff.
2. It leaves actionable, specific comments directly on the GitHub PR lines/files.
3. Once the full review is complete, the Code Review Agent hands back control to the **Developer Agent**.

### Step 3: Revisions & Responses
1. The **Developer Agent** processes the review comments left on the PR.
2. For each comment, the Developer Agent must:
   - Fix the issue and push the new commits to the PR branch.
   - OR, reply to the GitHub comment explaining why a change is not needed or proposing an alternative.
3. Once all comments have been addressed via commits or replies, the Developer Agent hands back control to the **Code Review Agent**.

### Step 4: Re-Review & Resolution
1. The **Code Review Agent** evaluates the new commits and the Developer Agent's replies.
2. If satisfied with a fix or explanation, the Code Review Agent explicitly **resolves** the relevant GitHub comment thread.
3. If issues remain, it leaves new comments (returning to Step 2).
4. If there are **no unresolved issues left**, the Code Review Agent approves the code review and hands back to the **Developer Agent** for the final time.

### Step 5: Merge & Sync
1. The **Developer Agent** verifies that the PR has been approved and that there are **zero unresolved comments**.
2. If the conditions are met, the Developer Agent merges the PR via the GitHub CLI or API.
3. Following a successful merge, the Developer Agent syncs the local repository by:
   - Checking out the main branch.
   - Pulling the newly merged remote changes.
   - Deleting the local and remote feature branches to maintain a clean repository state.
