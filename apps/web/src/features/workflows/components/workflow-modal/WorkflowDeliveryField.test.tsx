// @vitest-environment jsdom
import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import type { BriefingScheduleState } from "@gaia/shared/types";
import { zodResolver } from "@hookform/resolvers/zod";
import type { WorkflowDelivery } from "@shared/api/generated";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithQueryClient } from "@/__tests__/helpers/queryClient";
import WorkflowDeliveryField from "@/features/workflows/components/workflow-modal/WorkflowDeliveryField";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
} from "@/features/workflows/schemas/workflowFormSchema";

const { getSchedule } = vi.hoisted(() => ({ getSchedule: vi.fn() }));
vi.mock("@/lib/api/typed", () => ({
  api: { get: () => getSchedule() },
}));

function schedule(
  frequency: BriefingScheduleState["frequency"],
): BriefingScheduleState {
  const daily = frequency === "daily" || frequency === "weekdays";
  return {
    frequency,
    hour: 8,
    paused_for_plan: false,
    next_daily_brief_at: null,
    has_daily_brief: daily,
    daily_brief_hour: daily ? 8 : null,
  };
}

const READY_BUT_DELIVERY: WorkflowFormData = {
  ...getDefaultFormValues(),
  title: "Morning digest",
  prompt: "Summarize my unread email",
};

function DeliveryForm({
  onValid,
  delivery,
}: {
  onValid: (data: WorkflowFormData) => void;
  delivery?: WorkflowDelivery;
}) {
  const { control, handleSubmit } = useForm<WorkflowFormData>({
    resolver: zodResolver(workflowFormSchema),
    defaultValues: delivery
      ? { ...READY_BUT_DELIVERY, delivery }
      : READY_BUT_DELIVERY,
  });
  return (
    <form onSubmit={handleSubmit(onValid)}>
      <WorkflowDeliveryField control={control} />
      <button type="submit">Create Workflow</button>
    </form>
  );
}

const renderForm = (delivery?: WorkflowDelivery) => {
  const onValid = vi.fn();
  renderWithQueryClient(<DeliveryForm onValid={onValid} delivery={delivery} />);
  return { onValid };
};

const briefButton = () =>
  screen.getByRole("button", { name: "Add to my brief" });

const NO_DAILY_BRIEF =
  "You get no daily brief, so there's no brief to add results to.";

describe("WorkflowDeliveryField", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSchedule.mockResolvedValue(schedule("daily"));
  });

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

  describe("adding a workflow's results to the brief", () => {
    it("is offered against the next daily brief while daily briefs are on", async () => {
      getSchedule.mockResolvedValue(schedule("weekdays"));
      renderForm("brief");

      expect(
        await screen.findByText("Results wait for your next daily brief."),
      ).toBeTruthy();
      expect(briefButton().hasAttribute("disabled")).toBe(false);
    });

    it.each(["off", "weekly_only"] as const)(
      "is unavailable, with the reason and the way back, when the schedule (%s) has no daily brief",
      async (frequency) => {
        getSchedule.mockResolvedValue(schedule(frequency));
        renderForm("now");

        expect(await screen.findByText(NO_DAILY_BRIEF)).toBeTruthy();
        expect(briefButton().hasAttribute("disabled")).toBe(true);
        expect(
          screen
            .getByRole("link", { name: "Turn on daily briefs" })
            .getAttribute("href"),
        ).toBe("/settings/briefings");
      },
    );

    it("says once why a workflow already set to the brief has nowhere to go", async () => {
      getSchedule.mockResolvedValue(schedule("off"));
      renderForm("brief");

      expect(await screen.findAllByText(NO_DAILY_BRIEF)).toHaveLength(1);
      expect(
        screen.queryByText(WORKFLOW_DELIVERY_COPY.brief.description),
      ).toBeNull();
    });
  });
});
