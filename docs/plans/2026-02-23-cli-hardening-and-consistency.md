# CLI Hardening And Consistency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate remaining CLI logic pitfalls (mode gating, unsafe process stop behavior, stale log streaming, version drift, and docs/frontend drift) while keeping command UX simple and predictable.

**Architecture:** Keep `gaia` as the single operator interface, but tighten mode-aware checks and lifecycle management in `packages/cli/src`. Introduce a small command metadata source to reduce docs/frontend drift and enforce behavior with lightweight CLI smoke tests.

**Tech Stack:** TypeScript, Commander, Ink, Node child_process, pnpm, shell smoke tests (`packages/cli/test-cli.sh`), MDX docs, Next.js frontend.

---

### Task 1: Make Prerequisite Checks Mode-Aware

**Problem observed:** `runPrerequisiteChecks()` always checks/installs Mise before setup mode is selected, which is unnecessary for self-host users.

**Files:**
- Modify: `packages/cli/src/lib/flow-utils.ts`
- Modify: `packages/cli/src/commands/init/flow.ts`
- Modify: `packages/cli/src/commands/setup/flow.ts`
- Test: `packages/cli/test-cli.sh`

**Step 1: Add split prerequisite functions**

Add separate functions in `flow-utils.ts`:
- `runBasePrerequisiteChecks()` -> checks Git + Docker only
- `runDeveloperPrerequisiteChecks()` -> checks Mise only (no self-host path)

**Step 2: Update flow order**

In init/setup flows:
1. Run base checks
2. Ask setup mode
3. Run developer checks only when mode is `developer`

**Step 3: Add smoke assertion (manual test path)**

In `packages/cli/test-cli.sh`, add a note/assertion that self-host setup should not fail on missing Mise.

**Step 4: Verify behavior**

Run:
```bash
pnpm -C packages/cli build
```
Expected: build succeeds.

Manual validation:
- Self-host mode path proceeds without requiring Mise.
- Developer mode still requires Mise.

---

### Task 2: Remove CLI Version Drift

**Problem observed:** `packages/cli/src/index.ts` hardcodes `0.1.0`, which can drift from `packages/cli/package.json`.

**Files:**
- Modify: `packages/cli/src/index.ts`
- Test: `packages/cli/test-cli.sh`

**Step 1: Read version from package metadata**

Replace hardcoded `.version("0.1.0")` with runtime package version lookup (e.g., from `package.json`).

**Step 2: Add version consistency check**

In `test-cli.sh`, add a check that `gaia --version` matches `package.json` version.

**Step 3: Verify**

Run:
```bash
pnpm -C packages/cli build
```
Then:
```bash
node packages/cli/dist/index.js --version
```
Expected: output matches `packages/cli/package.json`.

---

### Task 3: Make `gaia stop` Safer (Avoid Killing Unrelated Processes)

**Problem observed:** fallback port-based kills (`8000/3000`) can terminate unrelated local processes.

**Files:**
- Modify: `packages/cli/src/lib/service-starter.ts`
- Modify: `packages/cli/src/index.ts`
- Modify: `packages/cli/src/commands/stop/handler.ts`
- Modify: `packages/cli/src/commands/stop/flow.ts`

**Step 1: Default to PID/process-group stop only**

Use stored PID/process-group from GAIA-managed processes as primary and default stop behavior.

**Step 2: Add explicit force option for port cleanup**

Add CLI option:
- `gaia stop --force-ports`

Only run port-based cleanup when this explicit flag is provided.

**Step 3: Update stop UI/status text**

Show whether stop is running in safe mode vs force-port mode.

**Step 4: Verify**

Run:
```bash
pnpm -C packages/cli build
```
Manual test:
- `gaia stop` does not kill unrelated process bound to 3000/8000.
- `gaia stop --force-ports` performs aggressive cleanup.

---

### Task 4: Fix Stale Log Streaming Heuristic

**Problem observed:** `gaia logs` may tail stale `dev-start.log` even when no dev process is active.

**Files:**
- Modify: `packages/cli/src/commands/stream-logs/handler.ts`
- Modify: `packages/cli/src/lib/service-starter.ts`

**Step 1: Add process liveness check for dev PID**

Before tailing dev log, validate the saved dev PID/process group is still alive.

**Step 2: Fallback behavior when stale**

If dev PID is stale:
- Skip app log tail
- Stream Docker logs only
- Print clear message: run `gaia dev` for Nx foreground logs.

**Step 3: Verify**

Run:
```bash
pnpm -C packages/cli build
```
Manual test cases:
- Active dev process -> `gaia logs` streams app + docker logs
- Stale log file, dead process -> streams docker logs + clear hint

---

### Task 5: Prevent Docs/Frontend Command Drift

**Problem observed:** command descriptions and install guidance can diverge across CLI docs, developer docs, self-host docs, and install page.

**Files:**
- Create: `packages/cli/src/command-manifest.ts`
- Modify: `apps/web/src/app/(landing)/install/InstallPageClient.tsx`
- Modify: `docs/cli/commands.mdx`
- Modify: `docs/developers/commands.mdx`
- Modify: `docs/self-hosting/cli-setup.mdx`
- Test: `scripts/validate-cli-docs.sh` (new)

**Step 1: Add manifest for canonical command metadata**

Define command names + short descriptions in one source file.

**Step 2: Consume manifest in frontend install page**

Use manifest data for command table rendering.

**Step 3: Add validation script for docs**

Script checks that required commands (`init/setup/start/dev/dev full/logs/stop/status`) appear in key docs.

**Step 4: Verify**

Run:
```bash
pnpm -C packages/cli build
bash scripts/validate-cli-docs.sh
```
Expected: validation passes with no missing commands.

---

### Task 6: Add CLI Regression Smoke Tests For New Behavior

**Problem observed:** no automated guardrails for core behavior changes.

**Files:**
- Modify: `packages/cli/test-cli.sh`
- Create: `packages/cli/tests/cli-smoke.sh` (optional split)

**Step 1: Add smoke checks for command routing**

Cover:
- `gaia --help` shows `dev` and `logs`
- developer-mode `gaia start` errors with guidance
- `gaia dev full` is accepted profile
- invalid profile returns non-zero

**Step 2: Add expected output snippets**

Validate user-facing error/help text remains intentional.

**Step 3: Verify**

Run:
```bash
bash packages/cli/test-cli.sh
```
Expected: smoke checks pass.

---

## Risk Notes

- Workspace network instability can block package installs (`EAI_AGAIN`), so build/smoke steps should be runnable in a stable network CI job.
- Stop-behavior change is intentionally safer but changes previous “kill by port” behavior; communicate `--force-ports` in docs.

## Execution Order

1. Task 1 (mode-aware prerequisites)
2. Task 3 (safe stop behavior)
3. Task 4 (stale logs fix)
4. Task 2 (version source fix)
5. Task 5 (manifest + docs drift guard)
6. Task 6 (regression smoke tests)
