---
name: ck:plan
description: Plan a feature or system before implementation. Use when the user says "plan this", "I want to build X", "how do I implement Y", or when /ck:brainstorm produces a spec.md. Always run before /ck:cook. Modes (pick one): --fast (skip all, instant plan), --hard (2 researchers + red-team + validate), --two (2 approaches → compare → pick → cook), --parallel (parallel-impl plan → ck:cook --parallel), --auto (full pipeline + auto-cook), --archive (archive a completed plan). Composable flags: --no-test, --tdd — propagate into the cook pipeline.
user-invocable: true
---

# ck:plan — Structured Planning Pipeline

## Mode Reference

| Mode | Research | Red-Team | Validate | Cook handoff |
|------|----------|----------|----------|--------------|
| `--fast` | — | — | — | `/ck:cook --fast` |
| `--hard` | 2 researchers | ✓ | ✓ (wait) | `/ck:cook --hard` |
| `--two` | 2 researchers (one per approach) | ✓ both plans | pick A or B | `/ck:cook [user-chosen mode]` |
| `--parallel` | 2 researchers | ✓ | optional | `/ck:cook --parallel` |
| `--auto` | 1 researcher | ✓ | ✓ (wait) | auto-invoke cook (detected mode) |
| `--archive` | — | — | — | archive only, no cook |

**Auto-detect** (no flag given): Fast if single-file / familiar / ≤ 2 components; Hard otherwise.

---

### Step 0 — Archive Mode (early-return)

If `--archive` flag present:

1. Read `plan.md` — verify `**Status:** ✅ Done`. If not Done → stop: `[ERROR] Plan is not marked Done. Complete it with /ck:cook first.`
2. Copy entire `plans/{slug}/` → `plans/archive/{slug}/` (preserve all files).
3. Open or create `plans/archive/SUMMARY.md`; append entry:

```markdown
## {slug}

**Date:** {date from plan.md}
**Feature:** {feature name}
**Phases:** {count} — {comma-separated phase names}
**Key decisions:** {1–2 bullets from Key Decisions section, or "(none)"}
```

4. Report: `Archived → plans/archive/{slug}/` and updated `plans/archive/SUMMARY.md`.
5. **Stop** — do not continue to Step 1.

---

### Step 1 — Scope Challenge

Before spawning any agents, detect mode and challenge scope:

```
# Scope Challenge:
#   Exists?     → [does this feature already exist in the codebase?]
#   Minimum?    → [smallest impl that satisfies requirements]
#   Complexity? → [Fast | Hard | Two | Parallel | Auto]
#
# Mode: [detected or explicit]
# Test:  [default | --no-test | --tdd]
```

If scope is too large: suggest splitting and **wait for user confirmation**.

If `--hard` / `--two` / `--parallel` and novel/ambiguous with no brainstorm report: "No brainstorm found. Run `/ck:brainstorm` first? [Y/n]" — if Yes, stop; if No, proceed.

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

- **BLOCK**: resolve before proceeding
- **WARN**: user acknowledges — proceed
- **PASS**: continue

---

### Step 2 — Research

**`--fast`**: skip entirely.

**`--auto`**: spawn **1 `researcher` agent** — primary approach and best practices.

**`--hard` / `--parallel`**: spawn **2 `researcher` agents in parallel**:
- Instance A — role: `Primary` — recommended approach and best practices
- Instance B — role: `Alternative` — alternative approach and tradeoffs

**`--two`**: spawn **2 `researcher` agents in parallel**, each investigating one distinct approach:
- Instance A — role: `Approach A` — first viable approach (architecture, tradeoffs)
- Instance B — role: `Approach B` — second viable approach (meaningfully different strategy)

```
// Researcher A: [approach] → [verdict]
// Researcher B: [approach] → [verdict]
```

---

### Step 3 — Plan Creation

Spawn the **`planner` agent** with: feature description + mode + research reports + test flag + spec file path (if any).

- **`--tdd`**: planner adds `### Tests to Write First` to each phase, derived from spec acceptance criteria
- **`--no-test`**: planner notes `testing: skipped` in each phase header
- **Spec provided**: planner maps each phase to the P1/P2/P3 stories it covers
- **`--two`**: planner writes `plan-a.md` + `plan-b.md` (one per approach) — no `plan.md` yet
- **`--parallel`**: planner adds `## File Ownership` section to each phase file

Output structure:
```
plans/{slug}/
  plan.md            ← all modes except --two
  plan-a.md          ← --two only
  plan-b.md          ← --two only
  phase-01-{name}.md
  phase-02-{name}.md
  ...
```

---

### Step 4 — Red-Team Review

**`--fast`**: skip.

**All other modes**: spawn **`plan-reviewer`** with all plan files (+ spec.md if present).

**`--two`**: reviewer evaluates both plan-a and plan-b — flag risks in each separately.

Adjudicate each finding:
- `ACCEPTED` → edit the relevant plan file immediately
- `NOTED` → append to Risks section of plan.md
- `REJECTED` → document reason

If `plan-reviewer` returns `BLOCK`: revise the flagged phase and re-run before proceeding.

---

### Step 5 — Validation + Handoff

**`--fast`**: skip questions — output cook command immediately.

**`--two`**: present a side-by-side comparison, then wait for the user to pick:

```
## Approach Comparison
Plan A: {1-line summary}
  Pros: {key strengths}  |  Cons: {key tradeoffs}

Plan B: {1-line summary}
  Pros: {key strengths}  |  Cons: {key tradeoffs}

Which approach? [A/B]
```

After selection: ask 2–3 targeted questions about the chosen plan. Merge chosen plan into `plan.md`, delete the rejected file.

**`--hard` / `--parallel` / `--auto`**: ask 3–5 targeted questions about the plan's riskiest points. **Wait for user answers.**

After validation: hydrate tasks via TodoWrite. Recommend `--tdd` if spec.md exists and it's not already set.

Output the exact cook command:

| Mode | Cook command |
|------|-------------|
| `--fast` | `/ck:cook --fast [--no-test\|--tdd] plans/{slug}/plan.md` |
| `--hard` | `/ck:cook --hard [--no-test\|--tdd] plans/{slug}/plan.md` |
| `--two` | `/ck:cook [--fast\|--hard] [--no-test\|--tdd] plans/{slug}/plan.md` |
| `--parallel` | `/ck:cook --parallel [--no-test\|--tdd] plans/{slug}/plan.md` |
| `--auto` | Automatically invoke `/ck:cook --{detected-mode} plans/{slug}/plan.md` — no separate command |

---

## Agents

| Agent           | Step | Modes |
|-----------------|------|-------|
| `researcher`    | 2    | `--auto` (×1), `--hard`/`--parallel`/`--two` (×2 parallel) |
| `planner`       | 3    | All (except `--archive`) |
| `plan-reviewer` | 4    | All except `--fast`, `--archive` |
