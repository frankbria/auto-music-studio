# User Stories by Development Stage

**Project:** Auto Music Studio — AI Music Platform
**Version:** 1.0 Draft (April 2026)
**Methodology:** TDD, GitHub Issues per story, Agile/iterative delivery
**Reference:** [Platform Specification](../ai-music-spec.md) · [Model Deployment Guide](../model-deployment.md)

---

## Overview

This document defines user stories for the AI Music Platform organized into **28 development stages** across **4 layers**. The guiding principle is **build outward from a runnable core**:

1. **Layer 1 — CLI Foundation** (Stages 1–7): Every feature starts as a testable CLI command. The application runs locally, generates music, manages workspaces, processes audio, and exports for DAWs — all from the terminal.
2. **Layer 2 — Platform API** (Stages 8–14): CLI logic is wrapped in a FastAPI service with authentication, async job processing, remote compute, mastering, and distribution APIs.
3. **Layer 3 — Web UI** (Stages 15–21): A Next.js frontend consumes the API, providing the full creative and social experience.
4. **Layer 4 — Advanced Integrations** (Stages 22–28): VST3 plugin, music video, custom voice models, subscription/credits, moderation, and production polish.

**At every stage, the application runs.** A musician can use it — first via CLI, then via API calls, then through the browser, and finally from inside their DAW.

### How to Read This Document

- Each **stage** has an overview, a set of user stories, and stage completion criteria.
- Each **user story** contains: a user statement, a description, functional requirements (bullet points), and acceptance criteria (checkboxes).
- Stories are numbered `US-{stage}.{sequence}` (e.g., US-2.1 is the first story in Stage 2).
- **Stories are not exhaustive implementation specs.** They capture *what* and *why* — detailed technical design happens during implementation planning for each GH issue.
- Stages are sequential within a layer but some stages across layers can be parallelized (see [Dependency Graph](05-appendices.md#dependency-graph)).

### User Personas

| Persona | Description |
|---------|-------------|
| **Musician** | Primary user — creates, edits, produces, and distributes music. May range from hobbyist to professional producer. |
| **Listener** | Discovers, plays, and engages with music on the platform's social features. |
| **Admin** | Platform operator — moderates content, manages users, monitors system health. |
| **Developer** | Builds and maintains the platform — needs reliable tooling, CI/CD, and observability. |

### Development Methodology

- **TDD:** Tests are written before implementation. Acceptance criteria map directly to test assertions.
- **GitHub Issues:** Each user story becomes one or more GH issues when its stage is active. Issues are not pre-created for future stages. As of 2026-08-07 every story through Stage 28 — the last — has an issue, so the backlog is fully enumerated; new issues from here are follow-ups and post-launch work, not story creation.
- **Feature branches:** Each story/issue is developed on a feature branch and merged via PR to `main`.
- **Agile flexibility:** Stages define *intent*, not contracts. Stories may be added, modified, split, or deferred as learning happens during development.

#### Issue titles: `PX.Y` for order, `US-X.Y` for identity

They answer different questions, so both live in the title and neither replaces the other:

```
P1.1 US-26.3: Payment Integration
P2.3 Settle the VST3 SDK (Steinberg) licence before any public plugin build
```

- **`PX.Y` — required on every issue.** *When* to do it. `P1` is the current focus; higher tiers are later. Sorted component-wise as integers, so `P1.2` precedes `P1.10`. Re-assigned freely as priorities move — the number carries no history.
- **`US-X.Y` — only where a spec story exists.** *Which* story, per this document. Never changes, never renumbered. Follow-ups, tech debt, and post-launch work have no `US-` and don't get one invented; they say `(US-26.2 follow-up)` at the end of the title instead.

A stage's stories usually share a tier (Stage 27 → `P3.x`), but that is a consequence of the roadmap order, not a rule — priority is free to cut across stages when something earns it.

Since the spec ends at Stage 28, everything created from here is `PX.Y`-only.

---

## Stage Map

```
LAYER 1: CLI FOUNDATION
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 1  │→│ Stage 2  │→│ Stage 3  │→│ Stage 4  │→│ Stage 5  │→│ Stage 6  │→│ Stage 7  │
│ Bootstrap│  │Model CLI │  │Gen Params│  │Workspace │  │Audio Proc│  │Iterative │  │DAW Export│
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘

LAYER 2: PLATFORM API
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 8  │→│ Stage 9  │→│ Stage 10 │→│ Stage 11 │→│ Stage 12 │→│ Stage 13 │→│ Stage 14 │
│API Found.│  │Gen API   │  │Edit API  │  │Compute   │  │Mastering │  │Distrib.  │  │Export API│
└─────────┘  └─────────┘  └─────────┘  │Routing   │  │API       │  │API       │  └─────────┘
                                         └─────────┘  └─────────┘  └─────────┘

LAYER 3: WEB UI
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 15 │→│ Stage 16 │→│ Stage 17 │→│ Stage 18 │→│ Stage 19 │→│ Stage 20 │→│ Stage 21 │
│App Shell │  │Create UI │  │Edit UI   │  │Waveform  │  │Studio UI │  │Social UI │  │Master UI │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘

LAYER 4: ADVANCED INTEGRATIONS
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Stage 22 │  │ Stage 23 │→│ Stage 24 │  │ Stage 25 │  │ Stage 26 │→│ Stage 27 │→│ Stage 28 │
│Video Gen │  │VST3 Core │  │VST3 Adv. │  │Voice Mod.│  │Credits   │  │Moderat.  │  │Polish    │
└─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘
```

---

## Document Index

| File | Content | Stories |
|------|---------|--------|
| [01-layer-1-cli-foundation.md](01-layer-1-cli-foundation.md) | Stages 1–7: CLI Foundation | ~30 |
| [02-layer-2-platform-api.md](02-layer-2-platform-api.md) | Stages 8–14: Platform API | ~37 |
| [03-layer-3-web-ui.md](03-layer-3-web-ui.md) | Stages 15–21: Web UI | ~45 |
| [04-layer-4-advanced-integrations.md](04-layer-4-advanced-integrations.md) | Stages 22–28: Advanced | ~35 |
| [05-appendices.md](05-appendices.md) | Dependency Graph & Spec Cross-Reference | — |
