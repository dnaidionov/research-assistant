---
description: Formal execution steps defining the PR lifecycle handoff between the Developer and Code Review agents.
---

# Pull Request Code Review Lifecycle

This workflow strictly governs the cross-agent pull request feedback loop to enforce independent, unbiased code reviews before merging code on GitHub.

1. **Invoke Developer Agent**: The user (or upstream workflow) commands the `@developer` agent to write logic on a feature branch and subsequently use `gh pr create` to establish a PR.
// turbo
2. **Handoff to Reviewer (Developer)**: Once the PR is ready, the Developer Agent explicitly marks it ready for review (e.g. `gh pr ready`, or `gh pr edit --add-label "needs-review"`) and hands off control.
3. **Execution Context Isolation (Reviewer)**: The `@code-reviewer` agent initializes with an empty memory footprint. Before retrieving the PR diff, it must first execute `view_file` on `.agents/agents/code-reviewer.md`, `README.md`, and `docs/guidelines/antigravity-development-workflow.md` to reorient itself into the project constraints.
// turbo
4. **Initial Code Review (Reviewer)**: The Code Review Agent uses `gh pr diff` to explore the changes. It subsequently uses `gh pr comment` to leave detailed line-by-line feedback. *All comments must begin with the string `[Code Review Agent]:`.* Next, if issues exist, the Code Reviewer halts and explicitly notifies the Developer Agent that the review is complete, handing control back.
5. **Address Feedback (Developer)**: The Developer Agent resumes control. It fetches the PR comments using `gh`. It replies to threads or commits fixes and pushes them.
6. **Iterative Handoff**: The Developer marks the threads as addressed, invoking the Reviewer to perform a re-review (returning to Step 4).
7. **Resolution (Reviewer)**: During re-review, the Reviewer verifies the patches/explanations. If satisfactory, it resolves the specific GitHub comment threads (`gh pr comment --resolve` or via the web UI).
// turbo
8. **Final Approval (Reviewer)**: Once **zero unresolved issues** remain, the Code Review Agent approves the pull request via `gh pr review --approve` and yields a final time to the Developer.
// turbo
9. **Merge and Clean up (Developer)**: The Developer Agent asserts the PR is approved, executes `gh pr merge --squash --delete-branch`, checks out the `main` branch, and pulls the fresh history.
