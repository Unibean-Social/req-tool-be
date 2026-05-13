---
name: ck:plan
description: Plan a feature or system before implementation. Use when the user says "plan this", "I want to build X", "how do I implement Y", or when /ck:brainstorm produces a spec.md. Always run before /ck:cook. Auto-detects --fast (simple, single-file) vs --hard (multi-file, novel domain, security-sensitive). Flags --no-test and --tdd propagate into the cook pipeline.
user-invocable: true
---

# ck:plan — Structured Planning Pipeline

---

### Step 0 — Scope Challenge

Before spawning any agents, detect mode and challenge scope:

```
# Scope Challenge:
#   Exists?     → [does this feature already exist in the codebase?]
#   Minimum?    → [smallest impl that satisfies requirements]
#   Complexity? → [Fast | Hard] — reasons: multi-file? unfamiliar? security?
#
# Mode: [Fast | Hard]
# Test:  [default | --no-test | --tdd]
```

Mode auto-detection (override with explicit flag):
- **Fast** — single-file change, familiar pattern, ≤ 2 components
- **Hard** — multi-file, unfamiliar domain, security-sensitive, or ≥ 3 phases

If scope is too large: suggest splitting and **wait for user confirmation**.

If **Hard** and novel/ambiguous with no brainstorm report: "No brainstorm found. Run `/ck:brainstorm` first? [Y/n]" — if Yes, stop; if No, proceed.

If a spec file path is provided or `plans/{slug}/spec.md` exists adjacent to any plan: run a **Spec Quality Check** inline:

```
# Spec Quality Check:
#   [NEEDS CLARIFICATION] remaining? → CRITICAL — resolve before continuing
#   Success criteria measurable?     → HIGH if vague adjectives (fast, scalable, reliable)
#   User stories P1/P2/P3?           → HIGH if missing
#   Acceptance criteria testable?    → MEDIUM if vague ("works correctly")
#
# Verdict: [PASS | WARN (list) | BLOCK (list)]
```

- **BLOCK**: surface findings, resolve before proceeding
- **WARN**: list findings, user acknowledges — then proceed
- **PASS**: continue normally

---

### Step 1 — Research (Hard only)

Spawn **2 `researcher` agents in parallel**:
- **Instance A** — role: `Primary` — recommended approach and best practices
- **Instance B** — role: `Alternative` — alternative approach and tradeoffs

```
// Researcher A (Primary): [approach] → [verdict]
// Researcher B (Alternative): [approach] → [verdict]
```

---

### Step 2 — Plan Creation

Spawn the **`planner` agent** with: feature description + mode + research reports + test flag + spec file path (if any).

- **`--tdd`**: planner adds `### Tests to Write First` to each phase, derived from spec acceptance criteria
- **`--no-test`**: planner notes `testing: skipped` in each phase header
- **Spec provided**: planner maps each phase to the P1/P2/P3 stories it covers

Agent writes:
```
plans/{slug}/
  plan.md
  phase-01-{name}.md
  phase-02-{name}.md
  ...
```

---

### Step 3 — Red-Team Review (Hard only)

Spawn **`plan-reviewer`** with paths to all plan files (+ spec.md if present).

Adjudicate each finding:
- `ACCEPTED` → edit the relevant plan file immediately
- `NOTED` → append to Risks section of plan.md
- `REJECTED` → document reason

If `plan-reviewer` returns `BLOCK`: revise the flagged phase and re-run before proceeding.

---

### Step 4 — Validation + Handoff

Ask 3–5 targeted questions about the plan's riskiest points. **Wait for user answers.**

Hydrate tasks via TodoWrite, then recommend `--tdd` if spec.md exists and it's not already set.

Output the exact cook command:

```
Ready to cook:
/ck:cook [--fast | --hard] [--no-test | --tdd] plans/{slug}/plan.md
```

---

## Agents

| Agent           | Step | Modes |
|-----------------|------|-------|
| `researcher`    | 1    | Hard (×2 parallel) |
| `planner`       | 2    | All |
| `plan-reviewer` | 3    | Hard |
