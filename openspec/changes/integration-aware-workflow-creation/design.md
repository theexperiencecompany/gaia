## Context

Two creation paths currently feed the same step generator:

- **Onboarding** — `process_onboarding_intelligence` → `_create_onboarding_workflows` (`app/services/onboarding/intelligence_service.py`) plans 4 specs via `WORKFLOW_CREATION_PROMPT` (`app/agents/prompts/onboarding_prompts.py`), then for each spec calls `WorkflowService.create_workflow(generate_immediately=True)`. It passes **no** `selected_integrations`.
- **Manual** — `WorkflowModal` (`apps/web`) → `POST /workflows` → `WorkflowService.create_workflow`. The modal already has `IntegrationChipsSelector` and may send `selected_integrations`, but does not default to the user's connected set.

Both converge on `WorkflowGenerationService.generate_steps_with_llm` (`app/services/workflow/generation_service.py`). Today `selected_integrations`:
- **hard-filters** the tool registry to only those categories (lines ~170–200) — which also drops core categories like `search`; and
- appends a "prefer these" hint (lines ~231–238).

There is **no connection check** at generation time and **no workflow-level required/missing-integration computation** anywhere — only the route-level `require_integration()` dependency (`app/api/v1/dependencies/google_scope_dependencies.py`). Integration-**trigger** workflows already have a `pending_connection` path in `create_workflow` that sets `activated=False` when the trigger's integration is not connected; step-level integration needs have no equivalent.

Building blocks that already exist and will be reused:
- Category → integration: `ToolCategory.integration_name` / `require_integration` (`app/agents/tools/core/registry.py`); subagent integrations carry `subagent_config.tool_space` in `OAUTH_INTEGRATIONS` (`app/config/oauth_config.py`).
- Catalog: `OAUTH_INTEGRATIONS` + `get_integration_by_id`.
- Connected status: `get_all_integrations_status(user_id) -> dict[str, bool]` (cached 24h), `check_integration_status`.
- Frontend: `IntegrationChipsSelector`, `useIntegrations()` (returns full catalog with `status`, `slug`, `iconUrl`), `UnifiedWorkflowCard` / `ActivationStatus`, and the yellow-warning pattern in `IntegrationConnectionPrompt.tsx`.

## Goals / Non-Goals

**Goals:**
- One generation path and prompt for onboarding + manual creation, parameterized only by the preferred integration set.
- Generated steps prefer the right integrations, never propose unconnected-and-unnamed integrations, and include explicitly-named supported integrations even when unconnected.
- A workflow that needs an integration the user has not connected is created deactivated, cannot be activated, and is surfaced in the UI as disabled with a yellow warning + tooltip — instead of failing silently at run time.
- Onboarding captures the user's preferred integrations and anchors the 4 workflows to them.

**Non-Goals:**
- Auto-connecting integrations, or auto-activating workflows the moment a required integration is connected (user enables manually).
- Retroactively deactivating already-activated legacy workflows (we surface the warning but do not flip state in a read path).
- Changing the system-workflow provisioning mechanism (`provision_system_workflows`), the trigger model, or the execution agent.
- Per-tool granularity — gating is at integration granularity (the unit a user connects).

## Decisions

### D1. Replace the hard `selected_integrations` filter with a tiered palette; core capabilities are always present
`generate_steps_with_llm` builds the tool palette as:
1. **Core / non-integration categories** (`require_integration` false) — always included. This fixes the current bug where selecting `[notion]` strips `search`.
2. **Preferred integrations** — caller-supplied; their categories/subagents are included and the prompt biases toward them.
3. **Explicitly-named supported integrations** — see D2; included even if not preferred/connected.
Integrations outside (2)+(3) are **not** placed in the palette, so the model cannot route generic intent to an unconnected, unnamed integration.

The generation function's integration parameter is generalized from "filter list" to "preferred set" semantics. The persisted `Workflow.selected_integrations` field is retained as the stored preferred set (no schema change). Caller mapping:
- Onboarding: preferred = selected onboarding slugs (+ `gmail` if connected).
- Manual, explicit selection given: preferred = that selection.
- Manual, no selection: preferred = user's connected integration slugs (defaulted **server-side** in `create_workflow` for non-system workflows, so every client benefits from one source of truth).

*Alternative considered:* keep filtering but always re-add core categories. Rejected — it doesn't express the "named-but-unconnected" or "never-suggest" rules, which need explicit palette tiers + prompt direction.

### D2. Deterministic extraction of explicitly-named integrations
Before generation, scan the user's prompt/description for supported-catalog integrations by matching against each `OAuthIntegration` `id`, `name`, `short_name` (word-boundary, case-insensitive). Matches are added to the palette as **must-include**, and the prompt is told to include them. Anything not matched and not connected stays out of the palette.

*Why deterministic rather than handing the model the full catalog labeled "only if named":* it gives a hard guarantee for the "never suggest unconnected unless explicitly named" requirement (e.g. "research X" can never surface Perplexity) instead of relying on model restraint, and keeps the palette small. The gating layer (D3/D4) is the safety net if the model still emits an unexpected integration step.

*Trade-off:* matching is literal — a synonym the catalog doesn't list won't be detected. Acceptable because "explicitly names" implies the integration's actual name appears; the post-creation warning covers residual cases.

### D3. Required/missing integrations are derived, computed on read — never stored
A new module (e.g. `app/services/workflow/integration_requirements.py`) exposes:
- `compute_required_integrations(steps, trigger_config) -> set[str]` — map each `step.category` to an integration id via the registry (`integration_name` where `require_integration`) and via `OAUTH_INTEGRATIONS` subagent `tool_space`; add the trigger's integration when the trigger is an integration trigger; keep only ids present and `available` in the catalog.
- `compute_missing_integrations(required, user_id) -> list[IntegrationRef]` — `required` minus connected (`get_all_integrations_status`, fetched once per request), each entry hydrated from the catalog with `id`, `name`, `icon` for the UI.

`missing_integrations` (and `required_integrations`) are added to the workflow read responses (`GET /workflows`, `GET /workflows/{id}`, list, and the onboarding personalization response) and computed at read time. **No new persisted/derived state** → it can never go stale; connecting an integration clears the warning on next read.

*Alternative considered:* store `missing_integrations` on the workflow doc. Rejected — it drifts the moment connection state changes, exactly the bug class this change removes.

### D4. Activation gating, unified with the existing trigger `pending_connection` path
- **Creation** (`create_workflow`, both paths): after steps are generated, compute required→missing. If non-empty, persist `activated=False` and skip scheduling. This generalizes the current integration-trigger `pending_connection` handling so the trigger's integration and the steps' integrations are treated uniformly and both surface in `missing_integrations`.
- **Activation** (`POST /workflows/{id}/activate`): recompute missing; if non-empty, raise `AppError` naming the integrations to connect (fail loud per repo conventions) and leave the workflow deactivated.
- `generate_immediately=True` (onboarding) only generates steps synchronously; it does not execute. Blocked workflows stay `activated=False` and are never scheduled, so nothing runs against a missing integration.
- Already-activated legacy workflows are **not** flipped on read; their card shows the warning and re-activation is gated, but state is not mutated in a GET.

### D5. Onboarding flow & data threading
- **Stage**: insert an integration-selection stage after the Gmail step and before `processing` (the stage that triggers the intelligence job), in the onboarding wizard (`apps/web/src/app/[locale]/(main)/onboarding/`, `features/onboarding`). Continue is disabled until ≥3 selected (excluding Gmail). Gmail is auto-added to the preferred set when connected.
- **Transport/storage**: `OnboardingRequest` (`app/api/v1/endpoints/onboarding.py`) gains `selected_integrations: list[str]`; `complete_onboarding` stores it at `onboarding.selected_integrations` before `enqueue_intelligence_job`.
- **Generation**: `_create_onboarding_workflows` reads the stored slugs, injects them into `WORKFLOW_CREATION_PROMPT` (anchor the 4 specs around them) and passes them as the preferred set to each `create_workflow` call.

### D6. Frontend reuse, not rebuild
- Generalize `IntegrationChipsSelector` with a prop selecting the data source — `connected` (current behavior, manual modal) vs `catalog` (full supported list, onboarding) — sourced from the same `useIntegrations()` data; do not fork a second component (DRY).
- Drive the card state from `missing_integrations`: extend `ActivationStatus` / `UnifiedWorkflowCard` to render a yellow warning chip + `Tooltip` (matching `IntegrationConnectionPrompt` styling) and disable the run/activate controls when `missing_integrations` is non-empty. `useIntegrations()` is already imported in `UnifiedWorkflowCard`.
- Add `missing_integrations?: IntegrationRef[]` (and `required_integrations`) to the `Workflow` TS type; manual modal needs no selection change because the connected-set default lives server-side (D1).

## Risks / Trade-offs

- **Literal name matching for explicit mentions (D2)** misses unlisted synonyms / could match a common word that is also an integration name → Mitigation: match on `id`/`name`/`short_name` with word boundaries; the gating layer warns/disables regardless, so a miss degrades to "created disabled with warning," never to a silent runtime failure.
- **Model emits a step for an out-of-palette integration anyway** → Mitigation: D3/D4 catch it post-generation (workflow created disabled, warned); the palette restriction makes this unlikely.
- **Most onboarding workflows will be created disabled** (picked integrations are typically unconnected) → This is intended: the warning + connect CTA is the nudge to connect. Mitigation: clear copy so it reads as "ready once you connect," not "broken."
- **Per-read computation cost** for required/missing across a workflow list → Mitigation: `get_all_integrations_status` is cached (24h) and fetched once per request; category→integration resolution is in-memory.
- **Category→integration resolution depends on registry state** (provider categories register lazily) → Mitigation: resolve via the static `OAUTH_INTEGRATIONS` catalog (subagent `tool_space`) as the authoritative source, falling back to registry `integration_name` for non-subagent integration categories; never depend on a provider category having been lazily registered in the current process.

## Migration Plan

- Additive only: new `onboarding.selected_integrations` field and additive response fields; reuses the existing `Workflow.selected_integrations`. No data migration, no backfill.
- Rollout order: backend (generation generalization + requirements module + response fields + activation gating) → onboarding threading → frontend (selector + card warning). Frontend tolerates absent `missing_integrations` (treats as empty) so backend can ship first.
- Rollback: revert the generation-palette change and skip populating `missing_integrations`; cards fall back to the prior always-enabled state. No persisted state to unwind.

## Open Questions

- Should connecting a required integration **auto-activate** the workflows that were blocked on it, or require manual enable? Current decision: manual enable (matches the requested "remain disabled… connect to enable" behavior). Revisit if product wants auto-activation.
- For already-**activated** legacy workflows that now compute as having missing integrations: confirm we only warn (no state change) and leave them scheduled, vs. proactively notifying the user.
- Final source list for explicit-mention matching aliases (just `id`/`name`/`short_name`, or an extra alias list per integration for common phrasings like "gcal").
