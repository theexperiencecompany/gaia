// @vitest-environment jsdom
import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import { zodResolver } from "@hookform/resolvers/zod";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { describe, expect, it, vi } from "vitest";

import WorkflowDeliveryField from "@/features/workflows/components/workflow-modal/WorkflowDeliveryField";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
} from "@/features/workflows/schemas/workflowFormSchema";

const READY_BUT_DELIVERY: WorkflowFormData = {
  ...getDefaultFormValues(),
  title: "Morning digest",
  prompt: "Summarize my unread email",
};

function DeliveryForm({
  onValid,
}: {
  onValid: (data: WorkflowFormData) => void;
}) {
  const { control, handleSubmit } = useForm<WorkflowFormData>({
    resolver: zodResolver(workflowFormSchema),
    defaultValues: READY_BUT_DELIVERY,
  });
  return (
    <form onSubmit={handleSubmit(onValid)}>
      <WorkflowDeliveryField control={control} />
      <button type="submit">Create Workflow</button>
    </form>
  );
}

const renderForm = () => {
  const onValid = vi.fn();
  render(<DeliveryForm onValid={onValid} />);
  return { onValid };
};

describe("WorkflowDeliveryField", () => {
  it("names the missing choice and focuses it when the form is submitted without one", async () => {
    const { onValid } = renderForm();

    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    expect(
      await screen.findByText("Choose how you hear about each run"),
    ).toBeTruthy();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: WORKFLOW_DELIVERY_COPY.now.label }),
    );
    expect(onValid).not.toHaveBeenCalled();
  });

  it("clears the error once a delivery is picked and then submits it", async () => {
    const { onValid } = renderForm();
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));
    await screen.findByText("Choose how you hear about each run");

    fireEvent.click(
      screen.getByRole("button", { name: WORKFLOW_DELIVERY_COPY.silent.label }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Choose how you hear about each run"),
      ).toBeNull(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Create Workflow" }));

    await waitFor(() => expect(onValid).toHaveBeenCalledTimes(1));
    expect(onValid.mock.calls[0][0].delivery).toBe("silent");
  });

  it("stacks the segments on phones so every label fits", () => {
    renderForm();
    const group = screen.getByRole("group", { name: "When a run finishes" });
    expect(group.className).toContain("flex-col");
    expect(group.className).toContain("sm:flex-row");
  });

  it("explains the chosen delivery under the control, not between label and control", () => {
    renderForm();
    fireEvent.click(
      screen.getByRole("button", { name: WORKFLOW_DELIVERY_COPY.brief.label }),
    );
    const group = screen.getByRole("group", { name: "When a run finishes" });
    const helper = screen.getByText(WORKFLOW_DELIVERY_COPY.brief.description);
    expect(
      group.compareDocumentPosition(helper) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
