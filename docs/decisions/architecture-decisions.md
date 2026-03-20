# Architecture Decisions

## Decision 1: Separate repos per job

Reason:
- privacy isolation
- independent sharing
- audit integrity

Rejected:
- single monorepo

---

## Decision 2: Assistant repo contains no research data

Reason:
- safe to share publicly
- no accidental leaks

---

## Decision 3: Jobs linked via metadata, not submodules

Reason:
- simplicity
- avoids git complexity

Rejected:
- submodules
- symlinks as primary mechanism


---

## Decision 4: Local filesystem as source of truth

Reason:
- tool independence
- portability

---

## Decision 5: Obsidian as optional layer

Reason:
- navigation and synthesis only
- not canonical storage

---

## Decision 6: Claim-level audit required

Reason:
- reduces hallucination risk
- enforces traceability

## Decision 7: Codex as execution layer

Reason:
- supports multi-step workflows
- persistent state
- code evolution