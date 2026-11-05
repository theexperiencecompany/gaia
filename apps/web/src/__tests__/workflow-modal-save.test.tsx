// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createWorkflow = vi.fn();
const validateCron = vi.fn();
const dispatch = vi.fn();

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid: true, isUnknown: false }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

vi.mock("@/lib/analytics", () => ({
  track: vi.fn(),
}));

vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({ selectWorkflow: vi.fn() }),
}));

vi.mock("@/features/integrations/hooks/useIntegrations", () => ({
  useIntegrations: () => ({ integrations: [], connectIntegration: vi.fn() }),
}));

vi.mock("@/features/workflows/hooks/useWorkflowCreation", () => ({
  useWorkflowCreation: () => ({
    isCreating: false,
    error: null,
    createWorkflow: (...args: unknown[]) => createWorkflow(...args),
    clearError: vi.fn(),
  }),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: {
    validateCron: (...args: unknown[]) => validateCron(...args),
  },
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

import { initialWorkflowModalUiState } from "@/features/workflows/components/workflow-modal/modalState";
import { useWorkflowModalActions } from "@/features/workflows/components/workflow-modal/useWorkflowModalActions";
import type { WorkflowFormData } from "@/features/workflows/schemas/workflowFormSchema";

const SCHEDULED_FORM: WorkflowFormData = {
  title: "Morning digest",
  description: undefined,
  prompt: "Summarise my inbox",
  icon: null,
  icon_color: null,
  activeTab: "schedule",
  selectedTrigger: "",
  trigger_config: {
    type: "schedule",
    enabled: true,
    cron_expression: "0 9 * * *",
    timezone: "UTC",
  },
  notify_on_completion: true,
};

const BILLING = "The email is from a customer and is about billing";

const GMAIL_FORM: WorkflowFormData = {
  ...SCHEDULED_FORM,
  title: "Billing replies",
  prompt: "Draft a reply to the billing email",
  activeTab: "trigger",
  selectedTrigger: "gmail_new_message",
  trigger_config: {
    type: "integration",
    enabled: true,
    trigger_name: "gmail_new_message",
  },
  runs_only_when: BILLING,
};

describe("saving a new workflow", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    createWorkflow.mockResolvedValue({ success: false, workflow: null });
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const setup = (form: WorkflowFormData) =>
    renderHook(
      () =>
        useWorkflowModalActions({
          mode: "create",
          existingWorkflow: undefined,
          currentWorkflow: null,
          setCurrentWorkflow: vi.fn(),
          formData: form,
          triggerSchemas: [],
          hasPredefinedSteps: false,
          createAndSend: false,
          handleClose: vi.fn(),
          ui: initialWorkflowModalUiState,
          dispatch,
        }),
      { wrapper },
    );

  it("sends the create request once the server accepts the schedule", async () => {
    validateCron.mockResolvedValue({ valid: true });
    const { result } = setup(SCHEDULED_FORM);

    await act(() => result.current.handleSave(SCHEDULED_FORM));

    expect(validateCron).toHaveBeenCalledWith("0 9 * * *");
    expect(createWorkflow).toHaveBeenCalledTimes(1);
  });

  it("never sends the create request for a schedule the server refuses", async () => {
    validateCron.mockResolvedValue({
      valid: false,
      error: "Schedules can repeat at most once an hour.",
    });
    const { result } = setup(SCHEDULED_FORM);

    await act(() => result.current.handleSave(SCHEDULED_FORM));

    expect(createWorkflow).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenLastCalledWith({
      type: "phase",
      phase: "error",
    });
  });

  it("sends a drafted runs-only-when condition with an integration workflow", async () => {
    const { result } = setup(GMAIL_FORM);

    await act(() => result.current.handleSave(GMAIL_FORM));

    expect(createWorkflow.mock.calls[0]?.[0].runs_only_when).toBe(BILLING);
  });

  it("drops a drafted condition once the user moves the workflow onto a schedule", async () => {
    validateCron.mockResolvedValue({ valid: true });
    const form = { ...SCHEDULED_FORM, runs_only_when: BILLING };
    const { result } = setup(form);

    await act(() => result.current.handleSave(form));

    const request = createWorkflow.mock.calls[0]?.[0];
    expect(request).toBeDefined();
    expect(request.runs_only_when).toBeUndefined();
  });
});
