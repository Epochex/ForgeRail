# Interactive Game Build Lab Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute continuously under the user's explicit instruction to complete the work in one pass.

**Goal:** Deliver one local workbench with 16 executable fault/repair/verification cases, evidence and browser E2E.

**Architecture:** Modular FastAPI application, SQLite action journal and managed subprocess executor. Cases share the same context, lifecycle and evidence contracts. The existing build protocol remains compatible.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, native ES modules/CSS, Playwright test tooling.

**Spec:** `docs/superpowers/specs/2026-10-23-interactive-gamebuild-lab-design.md`

## Global Constraints

- One workbench, 16 cases, real local actions and browser E2E.
- No Unity Editor, Player, SDK installation, Docker or Jenkins launch.
- Success may say 构建成功 with an adjacent Lab badge; reports use `execution_mode: lab`.
- Local loopback only; bounded registered commands; no arbitrary path/command/URL input.
- One mutation per run, two active runs globally; idempotent requests and preserved evidence.
- Native ES modules follow the explicitly approved written spec; no application frontend dependencies.
- Every case includes prepare, inject, execute, diagnose, repair and verify; negative execution must be observed before repair.

## Review Focus

- Repeated requests and invalid action ordering must not duplicate side effects.
- Cancelling or restarting an action must not produce a false successful case.
- Evidence IDs and filesystem links must not allow reading outside the run.
- Independent fixture execution must establish runtime receipts, not write assumed success.
- Every registered variant needs an actual negative/repair/positive regression.

## File and interface map

- `lab/context.py`: `Context(root, case_id, variant, action, emit=None, cancelled=None)`; `repo`, `output`, `record(stage,status,message,**data)`, `stage(name)`, `command(argv,cwd=None,timeout=10,allow_failure=False)`, `write(relative,value)`, `read(relative)`, `commit(message)`, `check(label,passed,expected=None,actual=None)`, `result(summary,checks,**facts)`.
- `lab/catalog.py`: `CASES: list[dict]`, each with id/title/category/role/description/impact/variants/diagnosis/repair/interview/boundary. Variants are `{id,label}`.
- `lab/scenarios/`: `prepare(ctx)`, `inject(ctx)`, `execute(ctx)->dict`, `repair(ctx)` exported by dispatcher. Returned result has passed/summary/checks/facts; checks are actual assertions with observed values.
- `lab/store.py`: journal, run snapshots, action admission, idempotency, events and evidence.
- `lab/service.py`, `lab/runner.py`: managed action subprocesses, real-time events, cancellation and restart recovery.
- `lab/api.py`, CLI `lab`: authenticated same-origin service, artifacts and static UI.
- `lab/web/`: accessible workbench, API/state/view/evidence modules and styles.
- `tests/test_lab_*.py`, `tests/e2e/`: backend and real-browser acceptance.

### Task 1: Durable action execution and HTTP boundary

- [x] Write tests for unimplemented API auth, lifecycle, invalid order, idempotency, cancellation and restart recovery; observe import/behavior failures.
- [x] Implement journal and Context, then service/runner and loopback-only CLI.
- [x] Validate evidence confinement, origin rejection, independent action execution and preservation after restart.
- [x] Commit only this task's paths after tests pass.

### Task 2: Sixteen scenario families and all variants

- [x] Write a parameterized scenario test which prepares, injects, observes failed checks, repairs, verifies and inspects evidence; observe missing dispatcher failure.
- [x] Implement catalog and grouped modules using Context. Reuse Store, SourceManager, NodeLock, ContentCache, verify_package and probe_network where applicable.
- [x] Add explicit process receipts, Git conflict resolution, cache corruption, worker takeover, process-tree stop, release rollback, incremental patch and platform matrix checks.
- [x] Run all registered variants and record actual results; fix functional failures.

### Task 3: Single workbench and browser acceptance

- [x] Write browser tests for all 16 cases before adding the UI; initial server/page assertion must fail.
- [x] Build semantic sidebar, scene brief, six-step control, pipeline/real timing, linked evidence, before/after and history.
- [x] Add search/role filter, live polling, cancel, errors, export/download and mobile layout.
- [x] Run all default case workflows through real HTTP and browser clicks, plus repeated requests/cancellation/refresh/evidence/keyboard/mobile checks.

### Task 4: Review, packaging and handoff

- [x] Review code and scenario results against each spec requirement; fix important findings.
- [x] Run original and added Python suites plus full browser suite; inspect screenshots.
- [x] Update README, code map and an implementation retrospective with actual choices, alternatives, limitations and evidence.
- [x] Verify wheel contains frontend assets, git diff/secret checks, clean commit and remote sync.
- [x] Leave the lab runnable locally and provide launch link/command and results.

Implementation integrated after shared runtime/scenario/UI review, rather than committing partial imports. Local Python/browser/packaging acceptance completed; see docs/interactive-lab-validation.md. Final remote CI status is recorded separately.
