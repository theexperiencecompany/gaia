// @vitest-environment jsdom
import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import type { BriefingScheduleState } from "@gaia/shared/types";
import type { WorkflowDelivery } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowDeliveryField from "@/features/workflows/components/workflow-modal/WorkflowDeliveryField";
import {
  getDefaultFormValues,
  type WorkflowFormData,
} from "@/features/workflows/schemas/workflowFormSchema";
import { NotificationsAPI } from "@/services/api/notifications";

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getBriefingSchedule: vi.fn(),
    updateBriefingSchedule: vi.fn(),
  },
}));

function DeliveryOnly({ delivery }: { delivery: WorkflowDelivery }) {
  const { control } = useForm<WorkflowFormData>({
    defaultValues: { ...getDefaultFormValues(), delivery },
  });
  return <WorkflowDeliveryField control={control} />;
}

function renderField(
  schedule: Pick<BriefingScheduleState, "frequency" | "hour">,
  delivery: WorkflowDelivery,
) {
  vi.mocked(NotificationsAPI.getBriefingSchedule).mockResolvedValue({
    ...schedule,
    paused_for_plan: false,
    next_daily_brief_at: null,
  });
  return render(<DeliveryOnly delivery={delivery} />);
}

const briefButton = () =>
  screen.getByRole("button", { name: "Add to my brief" });

describe("adding a workflow's results to the brief", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is offered against the next daily brief while daily briefs are on", async () => {
    renderField({ frequency: "weekdays", hour: 8 }, "brief");

    expect(
      await screen.findByText("Results wait for your next daily brief."),
    ).toBeTruthy();
    expect(briefButton().hasAttribute("disabled")).toBe(false);
  });

  it.each(["off", "weekly_only"] as const)(
    "is unavailable, with the reason and the way back, when the schedule (%s) has no daily brief",
    async (frequency) => {
      renderField({ frequency, hour: 8 }, "now");

      expect(
        await screen.findByText(
          "You get no daily brief, so there's no brief to add results to.",
        ),
      ).toBeTruthy();
      expect(briefButton().hasAttribute("disabled")).toBe(true);
      expect(
        screen
          .getByRole("link", { name: "Turn on daily briefs" })
          .getAttribute("href"),
      ).toBe("/settings/briefings");
    },
  );

  it("says once why a workflow already set to the brief has nowhere to go", async () => {
    renderField({ frequency: "off", hour: 8 }, "brief");

    expect(
      await screen.findAllByText(
        "You get no daily brief, so there's no brief to add results to.",
      ),
    ).toHaveLength(1);
    expect(
      screen.queryByText(WORKFLOW_DELIVERY_COPY.brief.description),
    ).toBeNull();
  });
});
