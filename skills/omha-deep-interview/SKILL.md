---
name: omha-deep-interview
description: >
  Socratic requirements interview with mathematical ambiguity scoring. Asks targeted questions
  to reduce ambiguity below a threshold (default 0.2) before any planning or implementation
  begins. Use when goals are vague or underspecified.
version: 0.1.0
tags: [requirements, interview, ambiguity, specification]
category: omha
metadata:
  hermes:
    requires_toolsets: [terminal]
---

# OMHA Deep Interview — Ambiguity Gating

## Status: STUB — To Be Built

This skill will be designed using `omha-ralplan` consensus planning.

## When to Use

- When the goal is vague, underspecified, or could be interpreted multiple ways
- Before any planning or implementation on greenfield work
- When the user says: "deep interview", "what should we build", "help me think through this"
- When `omha-ralplan` determines the goal is too ambiguous to plan

## Planned Design

### Ambiguity Scoring (from OMC deep-interview)
- Goal Clarity: 40% weight
- Constraint Clarity: 30% weight
- Success Criteria: 30% weight
- Threshold: ≤ 0.2 to proceed (configurable)

### Interview Loop
- One focused question per round
- Score ambiguity after each answer
- At rounds 4+, activate challenge modes:
  - Contrarian (challenges assumptions)
  - Simplifier (finds the minimal version)
  - Ontologist (finds the essence)

### Output
- Specification written to `.omha/specs/interview-{timestamp}.md`
- Ambiguity score and dimension breakdown
- Detected by `omha-ralplan` and `omha-autopilot` to skip their own requirements phases

## TODO
- [ ] Design via ralplan consensus
- [ ] Implement interview loop
- [ ] Implement ambiguity scoring
- [ ] Implement challenge modes
- [ ] Test with real underspecified goals
