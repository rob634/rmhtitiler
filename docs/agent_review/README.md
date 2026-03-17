# Agent Review System

Multi-agent adversarial pipelines for code review, design, testing, and hardening of the geotiler tile server.

## Directory Structure

```
docs/agent_review/
├── README.md                    This file
├── CONSTITUTION.md              Architectural rules all agents must enforce
├── AGENT_RUNS.md                Run log — every pipeline execution with parameters, results, and token usage
├── siege_config_titiler.json    Test data, endpoints, attack payloads, and namespace definitions
├── agents/                      Pipeline definitions
│   ├── COMPETE_AGENT.md             Pipeline 1: Adversarial code review (Omega → Alpha + Beta → Gamma → Delta)
│   ├── REFLEXION_AGENT.md           Pipeline 2: Kludge hardening (R → F → P → J)
│   ├── GREENFIELD_AGENT.md          Pipeline 3: Design-then-build (S → A+C+O → M → B → V)
│   ├── SIEGE_AGENT.md               Pipeline 4: Sequential smoke test (Sentinel → Cartographer → Lancer → Auditor → Scribe)
│   ├── WAR_AGENT.md                 Pipeline 5: Red vs Blue state divergence (Strategist → Blue+Red → Oracle → Coroner)
│   ├── TOURNAMENT_AGENT.md          Pipeline 6: Full-spectrum adversarial (General → Pathfinder+Saboteur → Inspector+Provocateur → Tribunal)
│   ├── ADVOCATE_AGENT.md            Pipeline 7: Developer experience audit (Dispatcher → Intern → Architect → Editor)
│   ├── OBSERVATORY_AGENT.md         Pipeline 8: Diagnostic coverage assessment (Sentinel → Surveyor → Cartographer → Assessor → Scribe)
│   ├── ARB_AGENT.md                 Architecture Review Board — decomposes large builds into sequenced Greenfield runs
│   └── AGENT_METRICS.md             Instrumentation guide for token/quality tracking
└── agent_docs/                  Run outputs — full reports from each pipeline execution
```

## Pipelines

### Code Review & Build

#### COMPETE (Pipeline 1 — Adversarial Code Review)

Reviews existing code using information asymmetry between agents examining different scopes.

| Agent | Role |
|-------|------|
| Omega | Splits review into two asymmetric scopes |
| Alpha | Architecture and design review |
| Beta  | Correctness and reliability review (parallel with Alpha) |
| Gamma | Finds contradictions and blind spots between Alpha and Beta |
| Delta | Produces final prioritized, actionable report |

**Best for**: 5-20 file subsystems. Post-feature or architecture review sprints.

#### REFLEXION (Pipeline 2 — Kludge Hardening)

Hardens working-but-fragile code with minimal, surgical patches that preserve happy-path behavior.

| Agent | Role |
|-------|------|
| R | Reverse-engineers what the code does (gets NO documentation) |
| F | Finds every way the code can fail |
| P | Writes minimal patches for each fault |
| J | Judges each patch and plans deployment |

**Best for**: 1-5 files. Pre-deployment hardening or debugging recurring failures.

#### GREENFIELD (Pipeline 3 — Design-then-Build)

Designs and builds new code from intent. Stress-tests the design adversarially before coding.

| Agent | Role |
|-------|------|
| S | Formalizes intent into a spec (inline, no subagent) |
| A | Designs the system optimistically (parallel with C and O) |
| C | Finds what the spec does not cover (parallel with A and O) |
| O | Assesses operational and infrastructure reality (parallel with A and C) |
| M | Resolves conflicts between A, C, and O |
| B | Writes the code from M's resolved spec |
| V | Reverse-engineers the code blind (no spec) and compares to S's original |

**Best for**: New subsystems and features.

### Live Testing

#### SIEGE (Pipeline 4 — Sequential Smoke Test)

Fast linear verification of all tile server endpoints after deployment.

| Agent | Role |
|-------|------|
| Sentinel | Reads config, verifies health endpoint |
| Cartographer | Probes all endpoints, maps API surface |
| Lancer | Executes canonical read chain sequences |
| Auditor | Cross-validates metadata consistency |
| Scribe | Synthesizes final report |

**Best for**: Post-deployment confidence check. "Did that deploy break anything?"

#### WARGAME (Pipeline 5 — Red vs Blue State Divergence)

Focused adversarial testing of tile server state consistency: connection pools, token refresh, TiPG catalog, response determinism.

| Agent | Role |
|-------|------|
| Strategist | Defines campaign, writes Blue + Red briefs |
| Blue | Executes golden-path read chains with state checkpoints (parallel with Red) |
| Red | Attacks pools, tokens, catalog, and response consistency (parallel with Blue) |
| Oracle | Re-executes Blue's chains, compares to checkpoints, cross-references Red attacks |
| Coroner | Root-cause analysis with reproduction steps |

**Best for**: Pre-release state integrity. Testing pool health, token refresh races, catalog consistency under adversarial conditions.

#### TOURNAMENT (Pipeline 6 — Full-Spectrum Adversarial)

Maximum-coverage adversarial testing across all service families with deliberate information asymmetry.

| Agent | Phase | Role |
|-------|-------|------|
| General | Setup | Defines campaign, writes 4 specialist briefs |
| Pathfinder | Phase 1 (parallel) | Executes canonical read chains with checkpoints |
| Saboteur | Phase 1 (parallel) | Executes adversarial attacks (concurrency, resource, identity, parameter, catalog) |
| Inspector | Phase 2 (parallel) | Audits health and state — does NOT see Saboteur's log |
| Provocateur | Phase 2 (parallel) | Tests input validation in isolation |
| Tribunal | Phase 3 | Correlates all findings, classifies and scores |

**Best for**: Full adversarial regression before QA handoff.

### API Quality

#### ADVOCATE (Pipeline 7 — Developer Experience Audit)

Evaluates API from the perspective of developers trying to integrate.

| Agent | Role |
|-------|------|
| Dispatcher | Defines test data, endpoint inventory |
| Intern | First-impressions friction log (junior dev, no docs) |
| Architect | Structured DX audit against REST best practices |
| Editor | Merges, deduplicates, prioritizes final report |

**Best for**: Pre-release API polish. Ergonomics when correctness is proven.

#### OBSERVATORY (Pipeline 8 — Diagnostic Coverage)

Assesses whether diagnostic endpoints provide sufficient information to diagnose problems without shell access.

| Agent | Role |
|-------|------|
| Sentinel | Verifies systems inventory |
| Surveyor | Static code analysis, maps diagnostic surface |
| Cartographer | Live probes every diagnostic endpoint |
| Assessor | Grades coverage per system |
| Scribe | Final report with coverage matrix |

**Best for**: Periodic observability audit. Pre-release diagnostic readiness.

### Orchestration

#### ARB (Architecture Review Board)

Decomposes large build intents into sequenced Greenfield runs with explicit dependency chains. Use when scope exceeds a single Greenfield run (>4-6 components, >3,000 lines).

## Pipeline Selection Guide

| Situation | Pipeline |
|-----------|----------|
| Just deployed, need quick confidence | **SIEGE** |
| Pre-release, need state integrity proof | **WARGAME** |
| Pre-QA, need full adversarial regression | **TOURNAMENT** |
| Reviewing existing code (5-20 files) | **COMPETE** |
| Hardening fragile code (1-5 files) | **REFLEXION** |
| Building new feature from scratch | **GREENFIELD** |
| Large system needing decomposition | **ARB** → multiple **GREENFIELD** |
| API ergonomics and DX polish | **ADVOCATE** |
| Diagnostic endpoint sufficiency | **OBSERVATORY** |

## How to Read AGENT_RUNS.md

Each run entry contains:
- **Run number and date**
- **Pipeline type**
- **Scope** — what subsystem or feature was tested/reviewed/built
- **Parameters** — endpoints hit, scope splits, attack categories
- **Result** — verdict, finding count, severity breakdown
- **Token usage** — per-agent breakdown and total
- **Commit** — resulting code commit (if applicable)
