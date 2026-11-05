// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createWorkflow = vi.fn();

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
    validateCron: () => Promise.resolve({ valid: true }),
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

vi.mock("@/features/workflows/components/WorkflowModal", () => ({
  default: () => null,
}));

import WorkflowDraftCard from "@/features/workflows/components/WorkflowDraftCard";
import { initialWorkflowModalUiState } from "@/features/workflows/components/workflow-modal/modalState";
import { useWorkflowModalActions } from "@/features/workflows/components/workflow-modal/useWorkflowModalActions";
import type { WorkflowFormData } from "@/features/workflows/schemas/workflowFormSchema";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

const BILLING = "The email is from a customer and is about billing";

const GMAIL_FORM: WorkflowFormData = {
  title: "Billing replies",
  description: undefined,
  prompt: "Draft a reply to the billing email",
  icon: null,
  icon_color: null,
  activeTab: "trigger",
  selectedTrigger: "gmail_new_message",
  trigger_config: {
    type: "integration",
    enabled: true,
    trigger_name: "gmail_new_message",
  },
  notify_on_completion: true,
  gate: { condition: BILLING, enabled: true },
};

const SCHEDULED_FORM: WorkflowFormData = {
  ...GMAIL_FORM,
  activeTab: "schedule",
  selectedTrigger: "",
  trigger_config: {
    type: "schedule",
    enabled: true,
    cron_expression: "0 9 * * *",
    timezone: "UTC",
  },
};

describe("a drafted runs-only-when condition", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    createWorkflow.mockResolvedValue({ success: false, workflow: null });
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const save = async (form: WorkflowFormData) => {
    const { result } = renderHook(
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
          dispatch: vi.fn(),
        }),
      { wrapper },
    );
    await act(() => result.current.handleSave(form));
    return createWorkflow.mock.calls[0]?.[0];
  };

  it("is sent with the create request of an integration workflow", async () => {
    const request = await save(GMAIL_FORM);

    expect(request.runs_only_when).toBe(BILLING);
  });

  it("is dropped when the user turns it off before the workflow exists", async () => {
    const request = await save({
      ...GMAIL_FORM,
      gate: { condition: BILLING, enabled: false },
    });

    expect(request).toBeDefined();
    expect(request.runs_only_when).toBeUndefined();
  });

  it("is dropped once the user moves the workflow onto a schedule", async () => {
    const request = await save(SCHEDULED_FORM);

    expect(request).toBeDefined();
    expect(request.runs_only_when).toBeUndefined();
  });

  it("is shown on the draft card", () => {
    const draft: WorkflowDraftData = {
      suggested_title: "Billing replies",
      suggested_description: "Drafts a reply to customer billing emails",
      prompt: "Draft a reply",
      trigger_type: "integration",
      trigger_slug: "GMAIL_NEW_GMAIL_MESSAGE",
      runs_only_when: BILLING,
    };

    render(<WorkflowDraftCard draft={draft} />);

    expect(screen.getByText(`Runs only when: ${BILLING}`)).toBeTruthy();
  });
});
