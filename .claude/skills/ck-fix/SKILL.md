---
name: ck:fix
description: Fix a bug using Scout → Diagnose → Fix → Review → Finalize. Use when the user pastes an error message, stack trace, or test failure, or says "fix this bug", "something's broken", "tests are failing", "I'm getting an error". Modes (pick one): --fast (trivial errors — lint, type, build — skip scout and review), --hard (mandatory review, no auto-approve).
user-invocable: true
---

# ck:fix — Structured Bug-Fix Pipeline

Modes — mutually exclusive, pick one (default = Standard: auto-approve if score ≥ 9.5 with 0 CRITICAL):
- **`--fast`** — trivial issues (lint, type errors, build errors); skip scout, review, docs
- **`--hard`** — mandatory review, no auto-approve

---

### Step 0 — Prerequisites + Scope

If no error message, stack trace, or concrete description provided:
→ "Paste the error message or stack trace." Wait before continuing.

```
# Scope:
#   Description: {what the user said}
#   Quick?      → {yes/no — reason}
#   Mode:       {Standard | Quick | Hard}
```

If `--fast` or clearly a build/compiler/lint error: skip Step 1 → go directly to Step 2.

---

### Step 1 — Scout

Spawn **`scout`** with the bug description:

- Greps for error patterns in logs and stack traces
- Reads affected source files and maps dependencies
- Checks recent git changes for related commits

```
// Evidence:
//   Error pattern: NullReferenceException at auth.ts:45
//   Affected files: auth.ts, session.ts
//   Recent change: commit a3f2b1 modified auth.ts (2h ago)
```

---

### Step 2 — Diagnose

Spawn **`debugger`** with the scout evidence report:

- Forms 2–3 hypotheses from the evidence
- Confirms or rejects each against the codebase
- Applies the minimal fix at the confirmed root cause

```
// Hypothesis A: null check missing in auth.ts:45 → CONFIRMED ✓
// Hypothesis B: race condition in session init   → REJECTED ✗
//
// Root cause: missing null guard on req.user before .validate()
// Fix applied: auth.ts:45
// Severity: HIGH | Scope: 1 file
```

---

### Step 3 — Review

**`--fast`**: skip → Step 4.

Spawn **`code-reviewer`**: correctness, security, regressions, code quality.

**Standard**: auto-approve if score ≥ 9.5 with 0 CRITICAL. Up to 3 fix/re-review cycles (different approach each), then escalate.
**`--hard`**: no auto-approve — human must explicitly approve before Step 4.

---

### Step 4 — Finalize (MANDATORY)

**`project-manager`** (skip `--fast`): sync plan progress if bug was tracked.
**`docs-manager`** (skip `--fast`): update docs if fix changes a public contract.
**`git-manager`** (always): conventional commit + ask to push.

```
// git-manager → fix(auth): add null guard on req.user before validate
//            → Push to remote? [y/N]
```

---

## Agents

| Agent             | Step | Modes                                  |
| ----------------- | ---- | -------------------------------------- |
| `scout`           | 1    | Standard, `--hard` (skip if `--fast`)  |
| `debugger`        | 2    | All                                    |
| `code-reviewer`   | 3    | Standard, `--hard` (skip for `--fast`) |
| `project-manager` | 4    | Standard, `--hard` (skip for `--fast`) |
| `docs-manager`    | 4    | Standard, `--hard` (skip for `--fast`) |
| `git-manager`     | 4    | Always (mandatory)                     |
