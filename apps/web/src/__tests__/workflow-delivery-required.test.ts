// @vitest-environment jsdom
/**
 * A new workflow has no default delivery: the form refuses to validate and the
 * save button stays disabled until the user picks one.
 */

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: { validateCron: vi.fn() },
}));

import { useWorkflowSaveGate } from "@/features/workflows/components/workflow-modal/useWorkflowSaveGate";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
} from "@/features/workflows/schemas/workflowFormSchema";

const filled = (delivery: WorkflowFormData["delivery"]): WorkflowFormData => ({
  ...getDefaultFormValues(),
  title: "Morning digest",
  prompt: "Summarise my inbox",
  delivery,
});

const saveDisabled = (formData: WorkflowFormData) =>
  renderHook(() =>
    useWorkflowSaveGate({
      mode: "create",
      existingWorkflow: null,
      formData,
      selectedIntegrationSlugs: [],
      missingTriggerIntegration: null,
      isCreating: false,
    }),
  ).result.current.isSaveDisabled();

describe("workflow delivery on a new workflow", () => {
  it("starts with nothing chosen", () => {
    expect(getDefaultFormValues().delivery).toBeNull();
  });

  it("refuses to validate without a choice", () => {
    const parsed = workflowFormSchema.safeParse(filled(null));

    expect(parsed.success).toBe(false);
    expect(parsed.error?.issues.map((issue) => issue.message)).toContain(
      "Choose how you hear about each run",
    );
  });

  it.each(["now", "brief", "silent"] as const)(
    "validates once %s is chosen",
    (delivery) => {
      expect(workflowFormSchema.safeParse(filled(delivery)).success).toBe(true);
    },
  );

  it("keeps save disabled until a delivery is chosen", () => {
    expect(saveDisabled(filled(null))).toBe(true);
    expect(saveDisabled(filled("now"))).toBe(false);
  });
});
