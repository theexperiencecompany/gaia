// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const activateWorkflow = vi.fn();
const deactivateWorkflow = vi.fn();
const toastInfo = vi.fn();
const selectWorkflow = vi.fn();
const connectIntegration = vi.fn();

let isPaid = false;
let isSubscriptionStatusLoading = false;

const WORKFLOW = {
  id: "wf_1",
  activated: false,
  integration_ids: [],
  missing_integrations: [],
  trigger_config: { type: "manual" },
} as unknown as import("@/features/workflows/api/workflowApi").Workflow;

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid, isLoading: isSubscriptionStatusLoading }),
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    info: (...args: unknown[]) => toastInfo(...args),
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {},
  trackEvent: vi.fn(),
}));

vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({ selectWorkflow }),
}));

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations: [], connectIntegration }),
}));

vi.mock("@/features/workflows/hooks/useWorkflowCreation", () => ({
  useWorkflowCreation: () => ({
    isCreating: false,
    error: null,
    createWorkflow: vi.fn(),
    clearError: vi.fn(),
  }),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: {
    activateWorkflow: (...args: unknown[]) => activateWorkflow(...args),
    deactivateWorkflow: (...args: unknown[]) => deactivateWorkflow(...args),
  },
}));

vi.mock("@/features/workflows/stores/workflowsStore", () => ({
  useWorkflowsStore: () => ({
    addWorkflow: vi.fn(),
    updateWorkflow: vi.fn(),
    removeWorkflow: vi.fn(),
    fetchWorkflows: vi.fn(),
    invalidateCache: vi.fn(),
  }),
}));

vi.mock("@/features/workflows/stores/workflowModalStore", () => ({
  useWorkflowModalStore: () => ({
    setCreationPhase: vi.fn(),
    setIsRegeneratingSteps: vi.fn(),
    setRegenerationError: vi.fn(),
    setIsActivated: vi.fn(),
    setIsTogglingActivation: vi.fn(),
  }),
}));

vi.mock("@/features/workflows/triggers/utils", () => ({
  findTriggerSchema: () => undefined,
}));

vi.mock("@/features/workflows/utils/integrationMentions", () => ({
  mentionedIntegrationIds: () => [],
}));

vi.mock("@/features/workflows/components/shared/workflowCardHelpers", () => ({
  missingIntegrationsMessage: () => "",
}));

import { useWorkflowModalActions } from "@/features/workflows/components/workflow-modal/useWorkflowModalActions";

describe("workflow activation toggle paywall gate", () => {
  beforeEach(() => {
    isPaid = false;
    isSubscriptionStatusLoading = false;
    vi.clearAllMocks();
  });

  const setup = () =>
    renderHook(() =>
      useWorkflowModalActions({
        mode: "edit",
        existingWorkflow: WORKFLOW,
        currentWorkflow: WORKFLOW,
        setCurrentWorkflow: vi.fn(),
        formData: {} as never,
        triggerSchemas: [],
        hasPredefinedSteps: false,
        createAndSend: false,
        handleClose: vi.fn(),
      }),
    );

  it("shows an upgrade toast and never calls activateWorkflow for a free user", async () => {
    isPaid = false;
    const { result } = setup();

    await result.current.handleActivationToggle(true);

    expect(activateWorkflow).not.toHaveBeenCalled();
    expect(toastInfo).toHaveBeenCalledTimes(1);
    expect(toastInfo.mock.calls[0][0]).toMatch(/GAIA Pro/i);
  });

  it("calls activateWorkflow for a paid user without a toast", async () => {
    isPaid = true;
    const { result } = setup();

    await result.current.handleActivationToggle(true);

    expect(activateWorkflow).toHaveBeenCalledWith("wf_1");
    expect(toastInfo).not.toHaveBeenCalled();
  });

  it("lets a free user deactivate a workflow (only enabling is gated)", async () => {
    isPaid = false;
    const { result } = setup();

    await result.current.handleActivationToggle(false);

    expect(deactivateWorkflow).toHaveBeenCalledWith("wf_1");
    expect(toastInfo).not.toHaveBeenCalled();
  });

  it("lets activation proceed while the subscription-status query is still loading (cold-cache race)", async () => {
    isPaid = false;
    isSubscriptionStatusLoading = true;
    const { result } = setup();

    await result.current.handleActivationToggle(true);

    // The backend is the backstop for a genuinely free user — a
    // not-yet-resolved query must never block a paying user's toggle.
    expect(activateWorkflow).toHaveBeenCalledWith("wf_1");
    expect(toastInfo).not.toHaveBeenCalled();
  });
});
