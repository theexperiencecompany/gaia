/** An explore API outage costs the homepage its server-rendered workflow icons, never the page. */
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useWorkflowIconElement } from "@/features/workflows/components/shared/WorkflowIconElements";
import { WORKFLOW_CARD_ICON_SIZE } from "@/features/workflows/constants/workflowIconStyle";

const { getExploreWorkflowsServer } = vi.hoisted(() => ({
  getExploreWorkflowsServer: vi.fn(),
}));

vi.mock("@/features/workflows/lib/serverWorkflowsApi", () => ({
  getExploreWorkflowsServer,
}));

vi.mock("@/app/[locale]/(landing)/client", () => ({
  default: function LandingPageClient() {
    const icon = useWorkflowIconElement("mail", null, WORKFLOW_CARD_ICON_SIZE);
    return <p>{icon === undefined ? "client icons" : "server icons"}</p>;
  },
}));

import LandingPage from "@/app/[locale]/(landing)/page";

describe("homepage explore workflows read", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders with client icons and logs the failure when the explore API errors", async () => {
    const outage = new Error("explore API returned 503");
    getExploreWorkflowsServer.mockRejectedValue(outage);
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);

    const html = renderToStaticMarkup(await LandingPage());

    expect(html).toContain("client icons");
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("explore workflows"),
      outage,
    );
  });
});
