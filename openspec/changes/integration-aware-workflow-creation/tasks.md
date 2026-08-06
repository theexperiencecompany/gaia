## 1. Backend — integration requirements module

- [x] 1.1 Create `app/services/workflow/integration_requirements.py` with `compute_required_integrations(steps, trigger_config) -> set[str]`: map each `step.category` to an integration id via the registry (`ToolCategory.integration_name` where `require_integration`) and via `OAUTH_INTEGRATIONS` subagent `tool_space`; add the trigger integration when `trigger_config.type == INTEGRATION`; keep only ids present and `available` in the catalog. Resolve via the static catalog first, registry second (per design D3).
- [x] 1.2 Add `compute_missing_integrations(required: set[str], user_id: str) -> list[IntegrationRef]` using `get_all_integrations_status(user_id)` (single cached call), returning entries hydrated from `OAUTH_INTEGRATIONS` with `id`, `name`, and icon for the UI. Define an `IntegrationRef` schema in `app/schemas`.
- [ ] 1.3 Verify with a throwaway script: build a fake workflow with `gmail` + `search` steps for a user without Gmail → `required == {"gmail"}`, `missing == [{id: "gmail", ...}]`; with `search`-only → `required == set()`. Confirm a core-only workflow yields no required integration.

## 2. Backend — generalize integration-aware step generation

- [x] 2.1 In `app/services/workflow/generation_service.py`, replace the hard `selected_integrations` category filter with the tiered palette (design D1): always include core/non-integration categories; include preferred integrations' categories/subagents; exclude integrations outside the preferred + explicitly-named set.
- [x] 2.2 Add deterministic explicit-mention extraction (design D2): match the prompt/description against catalog `id`/`name`/`short_name` (word-boundary, case-insensitive); add matches to the palette as must-include.
- [x] 2.3 Generalize the function's integration parameter from "filter" to "preferred set" semantics (keep persisting it to `Workflow.selected_integrations`). Update all call sites.
- [x] 2.4 In `app/agents/prompts/workflow_prompts.py`, add prompt direction: bias toward preferred integrations; MUST include explicitly-named supported integrations even if unconnected; NEVER introduce a step for an integration that is neither preferred nor named (use built-in web search for generic research). Follow `app/agents/prompts/CLAUDE.md` (no em dashes; human-writing guidance).
- [ ] 2.5 Verify by running generation for: (a) preferred `["notion"]`, goal involving research → steps still use built-in search; (b) prompt naming Slack with Slack unconnected → a Slack step appears; (c) "research X" with Perplexity unconnected and unnamed → no Perplexity step.

## 3. Backend — creation defaults, activation gating, response fields

- [x] 3.1 In `WorkflowService.create_workflow` (`app/services/workflow/service.py`), for non-system workflows with no explicit selection, default the preferred set to the user's connected integration slugs.
- [x] 3.2 After step generation in `create_workflow`, compute required→missing; if non-empty, persist `activated=False` and skip scheduling. Unify this with the existing integration-trigger `pending_connection` path so trigger and step integrations both flow into `missing_integrations`.
- [x] 3.3 In `POST /workflows/{id}/activate` (`app/api/v1/endpoints/workflows.py`), recompute missing; if non-empty, raise `AppError` naming the integrations to connect and leave the workflow deactivated.
- [x] 3.4 Add `required_integrations` and `missing_integrations` to the workflow response schema (`app/schemas`/`app/models`) and populate them on read in `GET /workflows`, `GET /workflows/{id}`, and the list endpoint (computed per request; do not persist).
- [ ] 3.5 Verify by running the API locally: create a manual workflow whose step needs an unconnected integration → response has `activated=false` and `missing_integrations` populated; calling activate returns the gating error; connect the integration (or simulate connected status) → read shows empty `missing_integrations` and activate succeeds.

## 4. Backend — onboarding threading

- [x] 4.1 Add `selected_integrations: list[str]` to `OnboardingRequest` and persist it at `onboarding.selected_integrations` in `complete_onboarding` (`app/services/onboarding/onboarding_service.py`) before `enqueue_intelligence_job`.
- [x] 4.2 In `_create_onboarding_workflows` (`app/services/onboarding/intelligence_service.py`), read the stored slugs, add `gmail` when connected, inject them into `WORKFLOW_CREATION_PROMPT` (`app/agents/prompts/onboarding_prompts.py`) to anchor the 4 specs, and pass them as the preferred set to each `create_workflow` call.
- [ ] 4.3 Verify by running the onboarding-intelligence job for a test user with selected slugs (none connected): the 4 created workflows reference those integrations in their steps, persist `selected_integrations`, and are created `activated=false` with `missing_integrations` populated.

## 5. Frontend — types and onboarding selection step

- [x] 5.1 Add `missing_integrations?: IntegrationRef[]` and `required_integrations?: IntegrationRef[]` to the `Workflow` TS type (`types/features/workflowTypes.ts`); add `IntegrationRef`. Add `selected_integrations` to the onboarding submit payload type.
- [x] 5.2 Generalize `IntegrationChipsSelector` (`features/workflows/components/workflow-modal/IntegrationChipsSelector.tsx`) with a source prop — `connected` (current behavior) vs `catalog` (full supported list from `useIntegrations()`) — without forking a second component.
- [x] 5.3 Add the onboarding integration-selection stage after the Gmail step and before processing (`features/onboarding`, onboarding wizard): use the generalized selector in `catalog` mode, disable continue until ≥3 selected (excluding Gmail), and include the selected slugs (+ Gmail when connected) in the onboarding submit payload.
- [ ] 5.4 Verify in the running web app: the new stage appears after Gmail, the full catalog is searchable, continue is blocked under 3 selections, and the submitted payload contains the expected slugs.

## 6. Frontend — workflow card disabled-with-warning state

- [x] 6.1 Extend `ActivationStatus` / `UnifiedWorkflowCard` (`features/workflows/components/shared/`) to render a yellow warning chip + `Tooltip` (matching `IntegrationConnectionPrompt` styling) listing the integrations to connect, and disable the run/activate controls, when `missing_integrations` is non-empty.
- [x] 6.2 Apply the same state to onboarding suggestion cards (the workflows stage in `features/onboarding`) since they render via the shared card.
- [ ] 6.3 Confirm the manual modal needs no selection change (connected-set default is server-side); remove any now-redundant client default if present.
- [ ] 6.4 Verify in the running web app: a workflow with missing integrations shows the warning, run/activate are disabled, the tooltip names the integrations; after connecting them, the warning clears and controls enable.

## 7. Quality gates

- [x] 7.1 `nx type-check api` and `nx lint api` pass.
- [x] 7.2 `nx run-many -t type-check --projects=web,desktop` and `nx run-many -t lint --projects=web,desktop` pass.
- [ ] 7.3 Manual end-to-end check: complete onboarding selecting 3 unconnected integrations → 4 workflows created disabled with warnings → connect one integration → its workflow becomes enable-able and activates.
