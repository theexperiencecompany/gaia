// @vitest-environment jsdom
import type {
  AuthoredGateView,
  SystemGateView,
  UpdateWorkflowRequest,
} from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createWorkflow = vi.fn();
const updateWorkflow = vi.fn();
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
    updateWorkflow: (...args: unknown[]) => updateWorkflow(...args),
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
import { useWorkflowSaveGate } from "@/features/workflows/components/workflow-modal/useWorkflowSaveGate";
import {
  NO_GATE,
  type WorkflowFormData,
  workflowToFormData,
} from "@/features/workflows/schemas/workflowFormSchema";
import type { Workflow } from "@/types/features/workflowTypes";

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
  gate: NO_GATE,
};

const BILLING = "The email is from a customer and is about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";

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
  gate: { condition: BILLING, enabled: true },
};

const GAIA_GATE: AuthoredGateView = {
  kind: "authored",
  condition: BILLING,
  author: "gaia",
  enabled: true,
  display_condition: BILLING,
  enforced: false,
  recent_skips: [],
};

const DESK_GATE: SystemGateView = {
  kind: "system",
  preset: "inbox_desk",
  enabled: true,
  display_condition: DESK_TEXT,
  enforced: true,
  recent_skips: [],
};

const gatedWorkflow = (gate: Workflow["gate"]): Workflow =>
  ({
    id: "wf_1",
    user_id: "u1",
    title: "Billing replies",
    description: "",
    prompt: "Draft a reply to the billing email",
    steps: [],
    trigger_config: {
      type: "integration",
      enabled: true,
      trigger_name: "gmail_new_message",
    },
    gate,
    activated: true,
    notify_on_completion: true,
    integration_ids: [],
  }) as unknown as Workflow;

describe("saving the workflow modal", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    createWorkflow.mockResolvedValue({ success: false, workflow: null });
    updateWorkflow.mockResolvedValue(null);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const setup = (form: WorkflowFormData, existing?: Workflow) =>
    renderHook(
      () =>
        useWorkflowModalActions({
          mode: existing ? "edit" : "create",
          existingWorkflow: existing,
          currentWorkflow: existing ?? null,
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

  it("drops a drafted condition the user turns off before the workflow exists", async () => {
    const form = {
      ...GMAIL_FORM,
      gate: { condition: BILLING, enabled: false },
    };
    const { result } = setup(form);

    await act(() => result.current.handleSave(form));

    const request = createWorkflow.mock.calls[0]?.[0];
    expect(request).toBeDefined();
    expect(request.runs_only_when).toBeUndefined();
  });

  it("drops a drafted condition once the user moves the workflow onto a schedule", async () => {
    validateCron.mockResolvedValue({ valid: true });
    const form = {
      ...SCHEDULED_FORM,
      gate: { condition: BILLING, enabled: true },
    };
    const { result } = setup(form);

    await act(() => result.current.handleSave(form));

    const request = createWorkflow.mock.calls[0]?.[0];
    expect(request).toBeDefined();
    expect(request.runs_only_when).toBeUndefined();
  });

  describe("editing the gate", () => {
    const saveEdit = async (
      workflow: Workflow,
      gate: WorkflowFormData["gate"],
    ): Promise<UpdateWorkflowRequest> => {
      const form: WorkflowFormData = { ...workflowToFormData(workflow), gate };
      const { result } = setup(form, workflow);
      await act(() => result.current.handleSave(form));
      return updateWorkflow.mock.calls[0]?.[1];
    };

    it("sends a rewritten condition as the gate", async () => {
      const request = await saveEdit(gatedWorkflow(GAIA_GATE), {
        condition: INVOICES,
        enabled: true,
      });

      expect(request.gate).toEqual({ condition: INVOICES, enabled: true });
    });

    it("sends only enabled false when the gate is turned off", async () => {
      const request = await saveEdit(gatedWorkflow(GAIA_GATE), {
        condition: BILLING,
        enabled: false,
      });

      expect(request.gate).toEqual({ enabled: false });
    });

    it("turns a system gate off without sending its wording", async () => {
      const request = await saveEdit(gatedWorkflow(DESK_GATE), {
        condition: DESK_TEXT,
        enabled: false,
      });

      expect(request.gate).toEqual({ enabled: false });
    });

    it("leaves an untouched gate out of the request", async () => {
      const request = await saveEdit(gatedWorkflow(GAIA_GATE), {
        condition: BILLING,
        enabled: true,
      });

      expect(request).toBeDefined();
      expect(request.gate).toBeUndefined();
    });

    it("removes the gate when its condition is cleared", async () => {
      const request = await saveEdit(gatedWorkflow(GAIA_GATE), {
        condition: "  ",
        enabled: true,
      });

      expect(request.gate).toBeNull();
    });

    it("adds a gate to a workflow that had none", async () => {
      const request = await saveEdit(gatedWorkflow(null), {
        condition: INVOICES,
        enabled: true,
      });

      expect(request.gate).toEqual({ condition: INVOICES, enabled: true });
    });
  });
});

describe("the editor's save button and the gate", () => {
  const saveDisabled = (workflow: Workflow, gate: WorkflowFormData["gate"]) => {
    const { result } = renderHook(() =>
      useWorkflowSaveGate({
        mode: "edit",
        existingWorkflow: workflow,
        formData: { ...workflowToFormData(workflow), gate },
        selectedIntegrationSlugs: [],
        missingTriggerIntegration: null,
        isCreating: false,
      }),
    );
    return result.current.isSaveDisabled();
  };

  it("stays off while the gate is as saved", () => {
    expect(
      saveDisabled(gatedWorkflow(GAIA_GATE), {
        condition: BILLING,
        enabled: true,
      }),
    ).toBe(true);
  });

  it("turns on for a rewritten condition", () => {
    expect(
      saveDisabled(gatedWorkflow(GAIA_GATE), {
        condition: INVOICES,
        enabled: true,
      }),
    ).toBe(false);
  });

  it("turns on when the gate is switched off", () => {
    expect(
      saveDisabled(gatedWorkflow(DESK_GATE), {
        condition: DESK_TEXT,
        enabled: false,
      }),
    ).toBe(false);
  });
});
