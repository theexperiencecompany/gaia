## Why

During onboarding GAIA generates 4 workflows from the user's profession, focus, and (optionally) Gmail signals, but with **no notion of which integrations the user actually wants to use** — `_create_onboarding_workflows` never passes `selected_integrations` into generation. The result is workflows the user may never run. At the same time, step generation hard-filters tools by `selected_integrations` (dropping even core capabilities like web search) and performs **no check** of whether the integrations a workflow needs are actually connected, so a workflow whose steps require an unconnected integration is created looking ready, gets scheduled, and silently fails at run time.

This change makes workflow creation integration-aware end to end: onboarding captures the integrations a user cares about, both onboarding and manual creation feed integration preferences into one shared generation prompt, and any workflow that needs an integration the user hasn't connected is created disabled with a clear "connect X to enable" warning instead of failing later.

## What Changes

- **Onboarding integration-selection step.** After the Gmail connection step, add an onboarding screen that asks the user to select at least 3 integrations they use most, using a searchable multi-select over the **full supported catalog** (not just connected ones). Selected slugs (plus Gmail when connected) are submitted with onboarding completion and stored on the user's onboarding record.
- **Onboarding workflows anchored to selected integrations.** `_create_onboarding_workflows` passes the selected integrations as the preference set into both the 4-spec planning prompt and each per-workflow step generation, so the 4 workflows are built around those integrations and their steps use them.
- **Generalized, integration-aware step generation (shared by onboarding + manual).** Replace the current hard `selected_integrations` category filter with a tiered palette: (a) **core / non-integration capabilities are always available** (web search, memory, todos, reminders, etc.); (b) a caller-supplied **preferred** integration set is biased toward; (c) integrations that are neither preferred nor explicitly named by the user are **not offered**. The prompt gains direction so that an integration the user explicitly names in their request is included even if not yet connected (provided the system supports it), while integrations the user has not connected and did not name are never suggested (e.g. never propose Perplexity for "research this" — use built-in web search).
- **Manual creation uses connected integrations as preference automatically.** For non-system (manually created) workflows, when no explicit selection is provided the backend defaults the preferred set to the user's currently connected integrations, reusing the same generation path as onboarding.
- **Required/missing integration computation + activation gating.** Add a deterministic mapping from a workflow's step categories (and its trigger) to the integrations it requires, compared against the user's connected set. Workflows with missing integrations are created **deactivated** and cannot be activated until those integrations are connected (activation is rejected, failing loud). `missing_integrations` is computed on read and added to workflow responses.
- **Disabled-with-warning workflow card UI.** Workflow cards (including onboarding suggestions) for workflows with missing integrations show a yellow warning, disable the run/activate controls, and explain via tooltip which integrations must be connected to enable the workflow.

## Capabilities

### New Capabilities
- `onboarding-integration-selection`: the onboarding step that collects the user's preferred integrations and threads them into onboarding workflow generation.
- `workflow-integration-preferences`: the shared, integration-aware step-generation behavior (tiered palette + preference/explicit-mention/never-suggest rules) used by both onboarding and manual workflow creation.
- `workflow-integration-gating`: computing the integrations a workflow requires vs. the user's connected set, gating activation on it, and surfacing missing integrations to the UI as a disabled-with-warning state.

### Modified Capabilities
<!-- None: no existing openspec specs cover workflows or onboarding (only fs-metrics-prometheus and tracked-todos-vfs exist). -->

## Impact

- **Backend (`apps/api`)**
  - `app/services/workflow/generation_service.py` — generalize `generate_steps_with_llm` integration handling (tiered palette, explicit-mention inclusion, always-on core categories).
  - `app/agents/prompts/workflow_prompts.py` — add preference / explicit-mention / never-suggest direction to the generation prompt.
  - `app/services/onboarding/intelligence_service.py` + `app/agents/prompts/onboarding_prompts.py` — pass selected integrations into spec planning and per-workflow creation.
  - `app/services/onboarding/onboarding_service.py` + `app/api/v1/endpoints/onboarding.py` + `OnboardingRequest` — accept/store selected integration slugs.
  - New workflow-integration module — `compute_required_integrations(steps, trigger)` and `compute_missing_integrations(workflow, user_id)` using `ToolCategory.integration_name`/`require_integration`, `OAUTH_INTEGRATIONS`, and `get_all_integrations_status`.
  - `app/services/workflow/service.py` + `app/api/v1/endpoints/workflows.py` — set `activated=False` on creation when integrations are missing; reject `activate` when missing; populate `missing_integrations` on read.
  - `app/schemas`/`app/models` workflow response — add `required_integrations` / `missing_integrations`.
- **Frontend (`apps/web`)**
  - `features/onboarding` — new integration-selection stage (reuse a generalized `IntegrationChipsSelector` that can browse the full catalog) wired into the onboarding wizard and submit payload.
  - `features/workflows/components/shared/UnifiedWorkflowCard.tsx` + `WorkflowCardComponents.tsx` — disabled + yellow warning + tooltip when `missing_integrations` is non-empty; gate run/activate.
  - `features/workflows/components/WorkflowModal.tsx` — default manual preference to connected integrations.
  - `types/features/workflowTypes.ts` + onboarding types — add `missing_integrations` / selection fields.
- **No database migration**: `missing_integrations` is computed per request from cached integration status; only the additive `onboarding.selected_integrations` field and the existing `Workflow.selected_integrations` field are persisted.
