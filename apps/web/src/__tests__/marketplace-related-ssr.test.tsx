// @vitest-environment jsdom
/**
 * Related sections must render real crawlable anchors from server-provided
 * data without any client fetch — this is what lands in the SSR HTML.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { IntegrationRelatedIntegrations } from "@/features/integrations/components/IntegrationRelatedIntegrations";
import { IntegrationRelatedWorkflows } from "@/features/integrations/components/IntegrationRelatedWorkflows";
import type { CommunityIntegration } from "@/features/integrations/types";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

vi.mock("next/image", () => ({
  default: () => null,
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function Providers({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

const RELATED: CommunityIntegration[] = [
  {
    integrationId: "notion",
    slug: "notion",
    name: "Notion",
    description: "Notes and docs",
    category: "productivity",
    iconUrl: null,
    cloneCount: 10,
    toolCount: 5,
    tools: [],
    publishedAt: null,
    creator: null,
  },
  {
    integrationId: "todoist",
    slug: "todoist",
    name: "Todoist",
    description: "Tasks",
    category: "productivity",
    iconUrl: null,
    cloneCount: 4,
    toolCount: 3,
    tools: [],
    publishedAt: null,
    creator: null,
  },
];

const WORKFLOWS: CommunityWorkflow[] = [
  {
    id: "wf-1",
    slug: "morning-briefing",
    title: "Morning briefing",
    description: "Daily digest",
    prompt: "Brief me",
    steps: [],
    created_at: new Date().toISOString(),
    creator: { id: "u1", name: "GAIA", avatar: null },
    categories: ["productivity"],
    total_executions: 3,
    icon: null,
    icon_color: null,
    source_integration: "slack",
    system_workflow_key: null,
    trigger_config: null,
  },
];

describe("IntegrationRelatedIntegrations SSR", () => {
  it("renders real marketplace anchors from initial data with no fetch", () => {
    render(
      <Providers>
        <IntegrationRelatedIntegrations
          currentSlug="slack"
          category="productivity"
          integrationName="Slack"
          initialIntegrations={RELATED}
        />
      </Providers>,
    );
    const links = screen.getAllByRole("link");
    const hrefs = links.map((link) => link.getAttribute("href"));
    expect(hrefs).toContain("/marketplace/notion");
    expect(hrefs).toContain("/marketplace/todoist");
    expect(hrefs).not.toContain("/marketplace/slack");
  });
});

describe("IntegrationRelatedWorkflows SSR", () => {
  it("renders real use-case anchors from initial data with no fetch", () => {
    render(
      <Providers>
        <IntegrationRelatedWorkflows
          integrationId="slack"
          integrationName="Slack"
          variant="section"
          initialWorkflows={WORKFLOWS}
        />
      </Providers>,
    );
    const links = screen.getAllByRole("link");
    const hrefs = links.map((link) => link.getAttribute("href"));
    expect(hrefs).toContain("/use-cases/morning-briefing");
  });
});
