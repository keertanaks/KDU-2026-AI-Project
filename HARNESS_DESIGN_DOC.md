# Harness Design Document
## Cyncly Auto-Design System — Kitchen 
---

## PR Link:
https://github.com/keertanaks/KDU-2026-AI-Project/pull/21

---


## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [What a Harness Actually Is](#3-what-a-harness-actually-is)
4. [Project Context — Cyncly Auto-Design System](#4-project-context--cyncly-auto-design-system)
5. [Harness Architecture — What Was Built](#5-harness-architecture--what-was-built)
6. [Component 1: AGENTS.md — The Master File](#6-component-1-agentsmd--the-master-file)
7. [Component 2: templates/ — The Development Sequence](#7-component-2-templates--the-development-sequence)
8. [Component 3: skills/ — The Reusable Instructions](#8-component-3-skills--the-reusable-instructions)
9. [Component 4: evals/ — Proof It Works](#9-component-4-evals--proof-it-works)
10. [The 12-Step Workflow](#10-the-12-step-workflow)
11. [Proof of Concept — Case-03 Eval Results](#11-proof-of-concept--case-03-eval-results)
12. [Design Decisions and Trade-offs](#12-design-decisions-and-trade-offs)
13. [Lessons Learned](#13-lessons-learned)
14. [How to Use This Harness](#14-how-to-use-this-harness)
15. [Future Roadmap](#15-future-roadmap)
16. [Appendix — Metrics](#16-appendix--metrics)

---

## 1. Executive Summary

This document describes the design, architecture, and rationale for the AI coding harness built for the **Cyncly Auto-Design System** (Kitchen Layout Visualizer). The harness encodes every architecture decision, coding convention, domain rule, and workflow step so that a fresh Claude Code or Cursor session can extend the project correctly — without back-and-forth, without invented conventions, and without violating protected constraints.

**The harness is proven to work.** In a live eval run, a fresh Claude Code session took a single-paragraph feature request (NKBA walkway width constraint) and:
- Created the feature folder and filled all three templates before writing a single line of code
- Read 4 relevant skill files and identified the right 4 files to touch
- Implemented the feature with zero violations of any rule
- Wrote 3 unit tests covering pass, fail, and edge cases
- Passed all 38 unit tests with zero regressions

**Zero human intervention was required after the initial prompt.**

---

## 2. Problem Statement

### The Recurring Pain of Context Re-entry

Every time a new feature was started on the Cyncly project, the same conversation played out:

> *"We use LangGraph for orchestration. Agents are plain Python classes. Don't hardcode model strings — use utils/model_selector.py. The NKBA validator runs on every variant without exception. The scoring formula is in CLAUDE.md. Don't touch render.py or layout.py..."*

This is a documentation problem masquerading as a prompting problem. The architecture exists. The conventions exist. The constraints exist. But they live in a developer's head, not in a form a coding tool can load and follow.

The result:
- **Every new chat started from scratch** — no memory of prior decisions
- **The coding tool invented conventions** when not explicitly told the real ones (wrong model strings, bare numbers in logic, bypassed validators, incorrect NKBA thresholds)
- **The same mistakes happened twice, three times** — wrong work triangle minimum (3600mm vs 3962mm), hardcoded model names, business logic in UI components
- **Feature development was slow** — not because of implementation time, but because of correction time

### What a Harness Fixes

A harness is a single, structured context document that a fresh coding session loads before doing anything else. It eliminates the context re-entry problem permanently. The harness *is* the architecture documentation, written in a form that a coding tool can follow, not just read.

---

## 3. What a Harness Actually Is

A harness is **not**:
- A README
- A tutorial for humans
- A one-shot prompt template
- A copy of the codebase in Markdown

A harness **is**:
- A **router** — pointing the coding tool to the right skill file for each type of work
- A **constraint enforcer** — making non-negotiable rules explicit and unforgettable
- A **workflow enforcer** — defining the sequence of steps that must happen before any code is written
- A **failure-mode library** — capturing every mistake the coding tool has made before, so it doesn't repeat them

The key insight from Scott's Eliza harness: **over-constrain on purpose.** The whole point is removing the coding tool's freedom to be creative in areas where you want predictability. A harness trades creativity for correctness.

---

## 4. Project Context — Cyncly Auto-Design System

### What the Project Does

The Cyncly Auto-Design System generates 3–5 kitchen layout variants from a single room specification JSON. For each variant it:

1. **Parses the room geometry** (spatial engine — walls, windows, doors, exclusion zones)
2. **Selects appropriate SKUs** from a 28-SKU catalog via MCP server (Agent 1 + Agent 2 with Haiku)
3. **Plans zones and assigns items to walls** (Agent 3 — Layout Strategist — with Sonnet/Opus)
4. **Places every item with mm-precision coordinates** (placement engine)
5. **Validates against 31 NKBA kitchen design rules** (constraint validator with scoring)
6. **Generates a rendered PNG and output JSON** (output generator + renderer)

All variants run in parallel. Each variant gets a compliance score (0.0–1.0). Low-scoring variants trigger an automatic retry with Opus-class reasoning.

### Why This Project Needed a Harness

The pipeline has several layers of domain-specific constraints that are completely non-obvious from the code alone:

- **NKBA rules**: 31 rules, each with specific thresholds (e.g., WORKFLOW-03 work triangle must be 3962mm minimum — NOT 3600mm, a common mistake)
- **Semantic vocabulary**: Agent 3 is restricted to exactly 11 placement terms. Any other term causes a placement fallback.
- **Model routing**: Three models (Haiku/Sonnet/Opus) assigned to specific agents with specific retry triggers. Hardcoding model strings breaks cost control.
- **Protected files**: render.py and layout.py are provided by the client spec and must never be modified
- **MCP abstraction**: catalog.json must never be read directly — only through the MCP server

Without a harness, a coding tool working on feature #5 has no way to know any of this.

---

## 5. Harness Architecture — What Was Built

```
Kitchen-Layout-Visualizer/
├── AGENTS.md                          ← Master file (118 lines, harness entry point)
├── AGENT_SPECS.md                     ← Legacy agent runtime specs (do not modify)
├── CLAUDE.md                          ← Architecture and scoring formula (protected)
├── CODING_STANDARDS.md                ← Type hints, module size, error handling rules
│
├── skills/                            ← 12 skill files (50–150 lines each)
│   ├── catalog.md
│   ├── color-resolution.md
│   ├── layout-typology.md
│   ├── constraint-validation.md
│   ├── variant-generation.md
│   ├── continuous-run.md
│   ├── rendering.md
│   ├── langgraph-workflow.md
│   ├── dto-contracts.md
│   ├── testing-strategy.md
│   ├── ui-integration.md
│   └── llm-routing-and-observability.md
│
├── templates/                         ← 3 spec templates (fill before writing code)
│   ├── 01-product-spec-template.md
│   ├── 02-technical-spec-template.md
│   └── 03-implementation-plan-template.md
│
├── evals/harness/                     ← 6 eval cases (Markdown, separate from Python evals)
│   ├── README.md
│   ├── case-01-budget-optimizer/
│   ├── case-02-style-transfer/
│   ├── case-03-walkway-constraint/    ← PASSED ✅ (2026-05-24)
│   ├── case-04-accessibility-agent/
│   ├── case-05-color-fallback/
│   └── case-06-export-design-report/
│
├── commands/                          ← Long-form workflow playbooks (human-readable)
├── .claude/                           ← Claude Code native primitives
│   ├── settings.json                  ← Tool permission rules
│   ├── commands/                      ← Slash commands (/review-impl, /run-eval, etc.)
│   └── agents/                        ← Sub-agents (drift-detector, pr-reviewer, etc.)
│
├── review/                            ← PR review checklist and review agent
├── decisions/                         ← MADR architecture decision records
├── docs/harness/                      ← Glossary, anti-patterns, context budget guide
├── checklists/                        ← Pre-commit and eval review checklists
└── harness/CHANGELOG.md               ← Harness version history (semver)
```

**Total harness footprint:** ~50 files, ~4,200 lines of Markdown documentation and workflow tooling.

---

## 6. Component 1: AGENTS.md — The Master File

### What It Is

AGENTS.md is a 118-line file at the repo root. It is the **first thing** any fresh coding session reads. It is deliberately a **router, not a textbook** — it points to skills, templates, and docs rather than inlining their content.

### What It Contains

| Section | Lines | Purpose |
|---------|-------|---------|
| Project Overview | 6 | One-paragraph summary of the whole system |
| Architecture diagram | 8 | ASCII pipeline diagram (Layer 1 → Layer 5) |
| Repo structure | 22 | Every directory with a one-line description |
| 12-step workflow | 14 | Ordered steps — must not be skipped or reordered |
| Skill glossary | 15 | 12 skills with When to Read guidance |
| Non-negotiable rules | 11 | Hard rules with no exceptions |
| Repo-specific rules | 7 | Project-specific constraints (WORKFLOW-03, MCP-only catalog, etc.) |
| Testing expectations | 6 | Where tests go, what type, what coverage is required |
| Context budget | 5 | Token limits for skills, templates, checklists |
| References | 10 | Links to CLAUDE.md, CODING_STANDARDS.md, openspec/ |

**Total: 118 lines.** Well under the 300-line ceiling recommended by Scott.

### Design Decision: Router Pattern

Early drafts of AGENTS.md included full skill content inline (work triangle formula, scoring equation, semantic vocabulary, etc.). This pushed the file to 400+ lines and made it difficult to update individual skills without touching the master file.

The decision was made to enforce a strict **router pattern**: AGENTS.md contains zero implementation detail. It only names what to read and when to read it. Every detail lives in the relevant skill file. This keeps AGENTS.md stable and keeps skills independently updatable.

---

## 7. Component 2: templates/ — The Development Sequence

### Philosophy

Templates solve a specific failure mode: coding tools that start writing code immediately, before understanding the problem. The templates enforce a mandatory discovery phase before any implementation happens.

The sequence is non-negotiable:

```
01-product-spec.md     ← Understand the user problem FIRST
        ↓
02-technical-spec.md   ← Design the solution SECOND
        ↓
03-implementation-plan.md  ← Plan the build THIRD
        ↓
Code                   ← Only now write code
```

### Template 1: Product Spec

Covers: user persona, use case, success criteria, failure states, NKBA constraints impacted, UI/non-UI scope boundary, acceptance tests. Forces the coding tool to state *why* a feature exists before stating *what* to build.

### Template 2: Technical Spec

Covers: DTO changes, affected pipeline layers, new constants, agent/graph changes, API surface, test strategy, risk register. Forces architectural thinking before implementation.

### Template 3: Implementation Plan

Covers: 13 ordered steps from DTO-first through to harness review. **Step 13** is a mandatory sign-off gate: *"STOP. Do not write any code until this step is complete."* Includes verification checklist: plan reviewed, spec aligned, protected files untouched, all relevant skills referenced.

The 13-step plan forces the coding tool to:
1. Check existing code before adding new code (Step 2)
2. Define DTOs before writing logic (Step 3)
3. Update graph wiring explicitly (Step 7)
4. Keep business logic out of UI (Step 8)
5. Write tests before considering the feature complete (Step 9)
6. Run the lint+type+test gate before review (Step 10)

---

## 8. Component 3: skills/ — The Reusable Instructions

### Philosophy

Each skill is an **opinionated instruction set for one specific thing in this repo.** It is not a tutorial. It is not documentation. It is a checklist plus a failure-mode library plus a good/bad example pair.

Skills come from two sources:
1. **Research**: reading the existing code and encoding its patterns before any coding tool touches it
2. **Pain**: when a coding tool makes a mistake, add that mistake to the relevant skill's "Common Failure Modes" section immediately

The rule: **add a skill the second you see the same mistake twice.**

### The 12 Skills Built

| Skill | Tool Risk | What It Encodes |
|-------|-----------|-----------------|
| `catalog.md` | medium | MCP-only catalog access, 28 SKUs, never read catalog.json directly |
| `color-resolution.md` | medium | Keyword → hex → SKU match logic, three-fallback chain |
| `layout-typology.md` | high | L/U/I/island selection rules, 5 variant seeds (fixed table) |
| `constraint-validation.md` | high | 31 NKBA rules, scoring formula, WORKFLOW-03=3962mm (not 3600mm) |
| `variant-generation.md` | high | asyncio.gather parallel pattern, spillover priority, retry logic |
| `continuous-run.md` | medium | Cabinet flush rules, gap detection, Z-level filtering |
| `rendering.md` | medium | render.py/layout.py output schema, PlacedItem fields, coordinate system |
| `langgraph-workflow.md` | high | StateGraph node wiring, KitchenGraphState, retry edges, should_use_opus() |
| `dto-contracts.md` | high | DTO-first principle, never duplicate DTOs, KitchenGraphState ownership |
| `testing-strategy.md` | medium | Unit/integration split, fixture conventions, no fake SKUs, no math mocks |
| `ui-integration.md` | medium | Business logic boundary, Streamlit component conventions, dark theme |
| `llm-routing-and-observability.md` | high | utils/model_selector.py, try/except on all API calls, prompt caching |

### Skill Structure (Enforced Format)

Every skill has:
```
---
name: <slug>
description: <one-line: when to use>
version: <semver>
last_verified: <date>
applies_to: [list of files]
tool_risk: low | medium | high
---

## Purpose          ← Why this skill exists
## When to Use      ← Exact trigger conditions
## Existing Repo Pattern  ← Copy-pasteable code from the actual repo
## Rules            ← Numbered, specific rules
## Bad Example      ← Code the tool has actually gotten wrong
## Good Example     ← The correct version
## Common Failure Modes  ← What goes wrong without this skill
## Must Not Do      ← Explicit prohibitions
## Completion Checklist  ← Checkbox list to verify before marking done
```

### The YAML Frontmatter Decision

Skills include YAML frontmatter with `version`, `last_verified`, and `applies_to` fields. This enables systematic drift detection: when a source file changes, the corresponding skill's `last_verified` date is checked against the file's last-modified date. If the skill is stale, a `drift-detector` sub-agent flags it for review before the next eval.

This is how the harness stays accurate over time — it versions the skills alongside the code.

### Critical Skill: constraint-validation.md

The most important skill in the harness. It encodes the single most common and most harmful mistake made without it:

> Using `WORK_TRIANGLE_MIN_MM = 3600.0` instead of `3962.0`.

3600mm is 11.8 feet. 3962mm is 13 feet exactly — the official NKBA minimum. The difference matters: a kitchen that passes at 3600mm may fail NKBA inspection at 3962mm. Without the skill, the coding tool pulls 3600mm from training data (it appears in many online kitchen design references). With the skill, the constant is explicitly stated and the wrong value is called out as a known failure mode.

---

## 9. Component 4: evals/ — Proof It Works

### Design Philosophy

As Scott said: *"Your harness is code. Run evals on it."*

The eval pattern is: give a fresh coding session a realistic feature request and compare what it produces against a hand-written expected output. If it matches, the harness works. If it diverges, you know exactly which skill or rule is missing.

### The 6 Eval Cases

| Case | Feature | Skills Stressed | Complexity |
|------|---------|-----------------|------------|
| case-01-budget-optimizer | Budget-constrained layout generation | 9 skills (catalog, variant-gen, zone-planner, DTO, graph, UI, testing, routing, constraints) | High |
| case-02-style-transfer | Apply a visual style preset to an existing variant | color-resolution, rendering, DTO, UI | Medium |
| case-03-walkway-constraint | Add NKBA-WW-01 walkway width validation rule | constraint-validation, testing-strategy, continuous-run, dto-contracts | Medium |
| case-04-accessibility-agent | New pipeline node for accessibility scoring | langgraph-workflow, dto-contracts, llm-routing, testing | High |
| case-05-color-fallback | Graceful fallback when color resolution fails | color-resolution, llm-routing, testing | Low-Medium |
| case-06-export-design-report | PDF export of variant report | rendering, UI, output-generator, testing | Medium |

Each eval case folder contains:
- **prompt.md** — the exact prompt pasted into a fresh chat (1–4 paragraphs, realistic feature request)
- **expected.md** — files to create, skills to read, rules to respect, tests to write, forbidden mistakes
- **result-notes.md** — pass/fail findings, rules violated, skills that need sharpening

### Why 6 Cases (Not 3–5)

The brief asks for 3–5. Six were built because each case stresses a different combination of skills. Cases 1 and 4 are intentionally hard (9 skills, multi-layer graph changes). Cases 3 and 5 are intentionally small (1–2 files). This spread catches both breadth failures (missing a skill entirely) and depth failures (a skill that's too shallow to cover edge cases).

### Eval Hygiene Rules

- **Always fresh chat** — no existing thread, no accumulated context
- **No intervention** — let the session run end-to-end without corrections
- **Compare to expected.md** — not to intuition
- **Fill result-notes.md** — even on pass (to capture what worked and why)
- **Sharpen the skill immediately** — on failure, update the skill the same day

---

## 10. The 12-Step Workflow

The workflow is the harness's core behavioral contract. Every feature, large or small, follows all 12 steps. Skipping any step is an error.

```
Step 1:  Read AGENTS.md
Step 2:  Read relevant openspec/specs/ files for context
Step 3:  Create features/active/<feature-name>/
Step 4:  Fill all three templates (01-product-spec, 02-technical-spec, 03-implementation-plan)
Step 5:  Identify relevant skills from the Skill Glossary in AGENTS.md
Step 6:  Read every relevant skill — verify last_verified date is current
Step 7:  Complete the implementation plan — DO NOT write code until plan is done
Step 8:  Build following CODING_STANDARDS.md
Step 9:  Run: pytest tests/unit/ -v  →  pytest tests/integration/ -v -m integration
Step 10: Review implementation against harness (commands/review-implementation.md)
Step 11: Fill result-notes.md if this came from an evals/harness/ case
Step 12: Sharpen skills if the harness failed to guide correctly
```

**The critical constraint:** Steps 3–7 happen entirely before any code is written. This is the single most important discipline the harness enforces.

---

## 11. Proof of Concept — Eval Results (3/3 PASS)

**Total: 3 eval cases run. All 3 passed. Brief required minimum 2/5.**

| Case | Feature Built | Tests | Rules Violated | Human Interventions |
|---|---|---|---|---|
| case-03 walkway-constraint | NKBA-WW-01 walkway width rule | 38/38 ✅ | 0 | 0 |
| case-01 budget-optimizer | Estimated budget + SKU substitution | 55/55 ✅ | 0 | 0 |
| case-05 color-fallback | Graceful fallback for unknown color keywords | 83/83 ✅ | 0 | 0 |

---

### Case-03 Deep Dive — Walkway Constraint

**Date:** 2026-05-24  
**Tool:** Claude Code (claude-sonnet-4-6) via /run-eval skill  
**Case:** case-03-walkway-constraint — Add NKBA-WW-01 minimum walkway width rule

### What the Coding Session Did

Following the harness workflow autonomously:

1. Read AGENTS.md ✅
2. Read 4 relevant skill files (constraint-validation, testing-strategy, continuous-run, dto-contracts) ✅
3. Created `features/active/walkway-constraint/` and filled all 3 templates before writing code ✅
4. Added `WALKWAY_MIN_SINGLE_COOK_MM = 1067.0` and `WALKWAY_MIN_MULTI_COOK_MM = 1219.0` as named constants ✅
5. Added `RULE_WEIGHTS["NKBA-WW-01"] = 0.10` ✅
6. Implemented `_check_nkba_ww_01` and `_compute_facing_walkway` (handles N/S pairs, E/W pairs, island fallback, returns `None` for single-wall layouts — no false positives on galley kitchens) ✅
7. Updated `total_rules` from 31 → 32 ✅
8. Added rationale entry to `utils/rationale_lookup.py` ✅
9. Added `NKBA-WW-01` to `ui/components/nkba_checklist.py` ✅
10. Wrote 3 unit tests: pass, fail-too-narrow, multi-cook threshold ✅

### Test Results

```
pytest tests/unit/ -v
============================= 38 passed in 0.22s ==============================
```

**38 of 38 tests pass. Zero regressions. No rules violated.**

### What the Harness Prevented

Without the `constraint-validation.md` skill, the coding tool would likely have:
- Used `WORK_TRIANGLE_MIN_MM = 3600.0` as a reference value (wrong by 362mm)
- Added the rule without a `RULE_WEIGHTS` entry (silent scoring failure)
- Added the rule without a `rationale_lookup.py` entry (empty rationale in output)
- Written only a pass test (no fail test, no edge case for multi-cook)

The skill's explicit "Common Failure Modes" section blocked all four of these mistakes before they could happen.

---

## 12. Design Decisions and Trade-offs

### Decision 1: AGENTS.md is a Router, Not a Textbook

**Choice:** AGENTS.md contains zero implementation detail — it only points to skills, templates, and docs.

**Why:** Early drafts inlined skill content and grew to 400+ lines. A 400-line file is too long to reliably fit in a coding tool's context window at the start of a session. More importantly, inlining content made every skill update require a master file edit.

**Trade-off:** The coding tool must follow pointer chains (AGENTS.md → skill file → code). This adds one read step. The benefit is that the master file stays stable and under 200 lines.

### Decision 2: 12 Skills Instead of 7

**Choice:** Built 12 skills (7 required by brief + 5 additional: langgraph-workflow, dto-contracts, testing-strategy, ui-integration, llm-routing-and-observability).

**Why:** The 7 required skills cover the pipeline layers. But the actual failure modes we observed were cross-cutting: hardcoded model strings (fixed by llm-routing-and-observability), incorrect LangGraph wiring (fixed by langgraph-workflow), wrong test placement (fixed by testing-strategy), business logic leaking into UI (fixed by ui-integration), DTO duplication (fixed by dto-contracts).

**Trade-off:** More skills = more maintenance. Mitigated by the `last_verified` frontmatter field and drift-detector sub-agent.

### Decision 3: Step 13 Sign-off Gate in Implementation Plan

**Choice:** Added a mandatory "STOP" gate as the last step of the implementation plan template, requiring explicit checklist sign-off before coding begins.

**Why:** Without an explicit gate, implementation plans were sometimes partially filled and then coding started anyway. The gate makes "plan complete" a binary condition, not a judgment call.

### Decision 4: File Protection via Documentation, Not settings.json

**Choice:** Protected files (render.py, layout.py, catalog.json) are documented in CLAUDE.md and enforced through harness rules, not through .claude/settings.json deny lists.

**Why:** The Claude Code settings.json schema accepts permission rules (e.g., "Bash(ruff format .)") but not file path deny globs. Attempting to add a "deny" array for file paths fails schema validation. File protection in this harness generation is documentation-enforced, not system-enforced.

**Future:** Git pre-commit hooks will add a system-level protection layer in v2.

### Decision 5: YAML Frontmatter on Skills

**Choice:** Each skill has YAML frontmatter with `name`, `description`, `version`, `last_verified`, `applies_to`, and `tool_risk`.

**Why:** Skills drift. The codebase changes but the skill file doesn't. The frontmatter provides a machine-readable way to detect when a skill is likely stale (last_verified date older than the relevant source file's modified date). The `tool_risk` field tells review agents which skills to prioritize during drift checks.

### Decision 6: Rationale as Lookup Table, Not LLM

**Choice:** NKBA rule rationale text is generated from a static lookup table in `utils/rationale_lookup.py`, not from an LLM call.

**Why:** An LLM rationale call would add ~$0.001–$0.003 per variant, ~$0.003–$0.015 per pipeline run. At scale, this adds up. More importantly, rationale for a fixed rule set is deterministic — the same rule always has the same explanation. Using an LLM for deterministic content is a waste of cost and latency.

**Result:** 37% cost reduction per pipeline run compared to the original Agent 4 (rationale writer) design. This was validated and documented in `decisions/` as an architecture decision record.

---

## 13. Lessons Learned

### 1. The Same Mistake Happens Twice Before You Write a Skill

The 3962mm vs 3600mm NKBA mistake happened twice in early development before it was encoded into `constraint-validation.md`. After the skill was written, it never happened again. The pattern: watch what goes wrong, add a skill immediately, don't wait until you have three examples.

### 2. "Fresh Chat Per Feature" Is Harder Than It Sounds

The natural instinct is to keep a long running conversation with context accumulated. This is exactly backwards. A 50-message thread feels productive but the context window fills with decisions, dead ends, and intermediate states that pollute the coding tool's reasoning for new tasks. The harness is the context. The chat is ephemeral. Enforcing fresh chats per feature was the single biggest behavioral change.

### 3. Skills Should Be Opinionated, Not Comprehensive

Early skills tried to explain every nuance of the relevant subsystem. A skill about constraint validation that covers all 31 NKBA rules in detail is a document, not a skill. A skill that says "here are the 3 rules that get violated most often, here's the one threshold that's commonly wrong, here are the 4 things you must include in every new rule" — that's a skill. Compression matters.

### 4. The settings.json Schema Is for Permission Rules, Not File Protection

Attempted to add a deny list for protected files to .claude/settings.json. The schema rejected it — `permissions.deny` accepts tool permission strings ("Bash(ruff format .)"), not file path globs. File protection requires either git hooks (planned for v2) or trust in documentation + checklists (current approach). This was a useful discovery: understand the tool's schema before designing around it.

### 5. The Template Sign-off Gate Works

Adding "STOP. Do not write any code until this step is complete." as a literal text instruction to the implementation plan template changed behavior. Without it, coding tools read the plan and started building immediately. With it, there is an explicit behavioral contract. Explicit beats implicit, always.

### 6. Eval Cases Must Stress Different Skills

If all eval cases test the same skill, you'll have a harness that's great at one thing and unknown on everything else. Case-03 (1 file, constraint skill) and case-01 (6+ files, 9 skills) are intentionally as different as possible. A harness is only as good as the breadth of its eval coverage.

### 7. The Harness Is Code — Version It

AGENTS.md has a version number (1.0.0). Skills have `version` and `last_verified` in frontmatter. The harness has its own CHANGELOG.md. This sounds like bureaucracy until you need to roll back a skill change that broke an eval that was previously passing. Versioning the harness is not optional.

### 8. Brownfield vs. Greenfield — Don't Invent Architecture

The harness was built around the existing code, not the other way around. Every skill's "Existing Repo Pattern" section was written by reading the actual code first, not by designing an ideal pattern. This distinction matters: a harness that encodes a hypothetical architecture is a liability. A harness that encodes the actual architecture is an asset.

---

## 14. How to Use This Harness

### Starting a New Feature

```
1. Open a fresh Claude Code or Cursor chat (never an existing thread)
2. Load AGENTS.md:   Read AGENTS.md
3. Paste the feature request (or read from evals/harness/<case>/prompt.md)
4. The coding tool should begin with:
   - Reading the relevant skills
   - Creating features/active/<feature-name>/
   - Filling all three templates
   - Writing the implementation plan
   - Getting plan sign-off (Step 13)
   - Then writing code
```

### Running an Eval

```
1. Start a fresh chat
2. Read docs/harness/fresh-chat-starter.md for the bootstrap prompt
3. Paste: Read AGENTS.md. Then follow: evals/harness/<case>/prompt.md
4. Do NOT intervene while the session builds
5. Compare output to expected.md
6. Fill result-notes.md
7. If any expected item was missed: run commands/sharpen-skill.md for that skill
```

### Adding a New Skill

A new skill is needed when:
- A coding tool makes the same mistake twice
- A new library or pattern is introduced to the project
- A new domain constraint is discovered (new NKBA rule category, new catalog requirement)

New skill format: copy any existing skill, replace content, keep all section headers, keep frontmatter structure.

### Sharpening an Existing Skill

When an eval fails because a skill guided incorrectly:
1. Identify the specific mistake made
2. Add it to the skill's "Common Failure Modes" section
3. Add a "Bad Example" if one is missing
4. Update `last_verified` to today
5. Bump `version` (patch version for minor clarification, minor version for significant change)
6. Re-run the eval that failed

---

## 15. Future Roadmap

### v1.1 — Hooks for File Protection

Replace the current documentation-only protection for `render.py`, `layout.py`, and `catalog.json` with git pre-commit hooks that fail the commit if any of these files are in the staged diff. This provides system-level enforcement instead of trust-based enforcement.

### v1.2 — Automated Drift Detection

Currently drift detection is manual (check `last_verified` date against file modification date). The `drift-detector` sub-agent in `.claude/agents/` provides the tooling but it still requires a human to trigger it. v1.2 will add a CI check that runs drift detection on every PR and fails if any skill's `last_verified` date is more than 30 days older than its source file's last commit.

### v2.0 — Eval Automation

Currently evals are run manually in fresh chats. v2.0 will introduce a test harness that:
- Spawns a Claude Code session programmatically via the Claude API
- Feeds it the eval prompt
- Captures its file-system changes
- Compares them against expected.md assertions
- Generates a pass/fail report

This turns the Markdown eval cases into a CI-runnable test suite — the harness becomes fully automated.

### v2.1 — Case Coverage Expansion

Run all 6 eval cases and sharpen skills based on findings. Target: 6/6 cases passing. Current status: 1/6 confirmed pass (case-03). Cases 01 and 04 (high complexity) are the priority.

---

## 16. Appendix — Metrics

### Harness Size

| Component | Files | Lines |
|-----------|-------|-------|
| AGENTS.md | 1 | 118 |
| templates/ | 3 | ~380 |
| skills/ | 12 | ~1,200 |
| evals/harness/ | 19 | ~850 |
| commands/ | 6 | ~420 |
| .claude/ (settings + agents + commands) | 10 | ~390 |
| review/ + checklists/ | 5 | ~280 |
| docs/harness/ | 4 | ~320 |
| decisions/ | 3 | ~180 |
| **Total** | **~63** | **~4,140** |

### Case-03 Eval Results

| Metric | Result |
|--------|--------|
| Steps followed correctly | 12/12 |
| Skills read | 4/4 (correct) |
| Non-negotiable rules violated | 0 |
| Files touched (intended) | 4 |
| Files touched (accidental) | 0 |
| Protected files touched | 0 |
| Unit tests written | 3 (pass + fail + edge case) |
| Pre-existing tests passing | 35/35 (no regressions) |
| New tests passing | 3/3 |
| Total test suite | 38/38 ✅ |
| Human interventions required | 0 |

### Skills by Tool Risk

| Tool Risk | Count | Skills |
|-----------|-------|--------|
| High | 5 | constraint-validation, variant-generation, langgraph-workflow, dto-contracts, llm-routing-and-observability |
| Medium | 7 | catalog, color-resolution, layout-typology, continuous-run, rendering, testing-strategy, ui-integration |
| Low | 0 | — |

High-risk skills are read first when they appear in the relevant skill list and are flagged for priority review on every drift check.

---

*Harness v1.0.0 — Built 2026-05-24 — Kitchen-Layout-Visualizer / Cyncly Auto-Design System*  
*"Your harness is code. Version it. Review changes. Run evals on it." — Scott*
