// @vitest-environment jsdom
import type {
  AuthoredGateView,
  SystemGateView,
  UpdateWorkflowRequest,
} from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateWorkflow = vi.fn();

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
    createWorkflow: vi.fn(),
    clearError: vi.fn(),
  }),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: {
    validateCron: () => Promise.resolve({ valid: true }),
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
import {
  type WorkflowFormData,
  workflowToFormData,
} from "@/features/workflows/schemas/workflowFormSchema";
import { RunsOnlyWhenField } from "@/features/workflows/triggers/components/RunsOnlyWhenField";
import type { Workflow } from "@/types/features/workflowTypes";

const BILLING = "the email is from a customer about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";

const GAIA_GATE: AuthoredGateView = {
  kind: "authored",
  condition: BILLING,
  author: "gaia",
  enabled: true,
  display_condition: BILLING,
  enforced: false,
};

const DESK_GATE: SystemGateView = {
  kind: "system",
  preset: "inbox_desk",
  enabled: true,
  display_condition: DESK_TEXT,
  enforced: true,
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

describe("the runs-only-when row", () => {
  const renderRow = (
    overrides: Partial<React.ComponentProps<typeof RunsOnlyWhenField>> = {},
  ) => {
    const props = {
      condition: BILLING,
      enabled: true,
      editable: true,
      enforced: true,
      onConditionChange: vi.fn(),
      onEnabledChange: vi.fn(),
      ...overrides,
    };
    render(<RunsOnlyWhenField {...props} />);
    return props;
  };

  it("hands each edit of the condition to its owner", () => {
    const { onConditionChange } = renderRow();

    fireEvent.change(screen.getByRole("textbox", { name: "Runs only when" }), {
      target: { value: INVOICES },
    });

    expect(onConditionChange).toHaveBeenCalledWith(INVOICES);
  });

  it("turns the gate off from its switch", () => {
    const { onEnabledChange } = renderRow();

    fireEvent.click(screen.getByRole("switch"));

    expect(onEnabledChange).toHaveBeenCalledWith(false);
  });

  it("shows a system gate's wording without letting it be rewritten", () => {
    renderRow({ condition: DESK_TEXT, editable: false });

    expect(screen.getByText(DESK_TEXT)).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("switch")).toBeTruthy();
  });

  it("says a rule still being checked skips no runs yet", () => {
    renderRow({ enforced: false });

    expect(
      screen.getByText(
        "GAIA is still learning this rule. Every event runs for now.",
      ),
    ).toBeTruthy();
  });

  it("says nothing about checking once the rule can skip runs", () => {
    renderRow({ enforced: true });

    expect(screen.queryByText(/still learning/)).toBeNull();
  });
});

describe("saving the workflow editor's gate", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    updateWorkflow.mockResolvedValue(null);
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const save = async (
    workflow: Workflow,
    gate: WorkflowFormData["gate"],
  ): Promise<UpdateWorkflowRequest> => {
    const form: WorkflowFormData = { ...workflowToFormData(workflow), gate };
    const { result } = renderHook(
      () =>
        useWorkflowModalActions({
          mode: "edit",
          existingWorkflow: workflow,
          currentWorkflow: workflow,
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
    return updateWorkflow.mock.calls[0]?.[1];
  };

  it("sends a rewritten condition as the gate", async () => {
    const request = await save(gatedWorkflow(GAIA_GATE), {
      condition: INVOICES,
      enabled: true,
    });

    expect(request.gate).toEqual({ condition: INVOICES, enabled: true });
  });

  it("sends only enabled false when the gate is turned off", async () => {
    const request = await save(gatedWorkflow(GAIA_GATE), {
      condition: BILLING,
      enabled: false,
    });

    expect(request.gate).toEqual({ enabled: false });
  });

  it("turns a system gate off without sending its wording", async () => {
    const request = await save(gatedWorkflow(DESK_GATE), {
      condition: DESK_TEXT,
      enabled: false,
    });

    expect(request.gate).toEqual({ enabled: false });
  });

  it("leaves an untouched gate out of the request", async () => {
    const request = await save(gatedWorkflow(GAIA_GATE), {
      condition: BILLING,
      enabled: true,
    });

    expect(request).toBeDefined();
    expect(request.gate).toBeUndefined();
  });

  it("removes the gate when its condition is cleared", async () => {
    const request = await save(gatedWorkflow(GAIA_GATE), {
      condition: "  ",
      enabled: true,
    });

    expect(request.gate).toBeNull();
  });

  it("adds a gate to a workflow that had none", async () => {
    const request = await save(gatedWorkflow(null), {
      condition: INVOICES,
      enabled: true,
    });

    expect(request.gate).toEqual({ condition: INVOICES, enabled: true });
  });
});
