import type { UserIntegration } from "../types/integrations";

export const IntegrationQueryKeys = {
  all: ["integrations"] as const,
  list: (params?: Record<string, unknown>) =>
    params
      ? ([...IntegrationQueryKeys.all, "list", params] as const)
      : ([...IntegrationQueryKeys.all, "list"] as const),
  detail: (integrationId: string) =>
    [...IntegrationQueryKeys.all, "detail", integrationId] as const,
  community: (params?: Record<string, unknown>) =>
    params
      ? ([...IntegrationQueryKeys.all, "community", params] as const)
      : ([...IntegrationQueryKeys.all, "community"] as const),
  userIntegrations: () =>
    [...IntegrationQueryKeys.all, "user"] as const,
};

export interface IntegrationStatusDisplay {
  label: string;
  color: string;
}

export function filterIntegrations(
  integrations: UserIntegration[],
  query: string,
): UserIntegration[] {
  if (!query.trim()) {
    return integrations;
  }

  const normalizedQuery = query.toLowerCase().trim();

  return integrations.filter((userIntegration) => {
    const { integration } = userIntegration;
    const matchesName = integration.name
      .toLowerCase()
      .includes(normalizedQuery);
    const matchesDescription = integration.description
      .toLowerCase()
      .includes(normalizedQuery);
    const matchesCategory = integration.category
      .toLowerCase()
      .includes(normalizedQuery);
    const matchesSlug = integration.slug
      .toLowerCase()
      .includes(normalizedQuery);

    return matchesName || matchesDescription || matchesCategory || matchesSlug;
  });
}

export function categorizeIntegrations(
  integrations: UserIntegration[],
): Record<string, UserIntegration[]> {
  const categories: Record<string, UserIntegration[]> = {};

  for (const userIntegration of integrations) {
    const category = userIntegration.integration.category;

    if (!categories[category]) {
      categories[category] = [];
    }
    categories[category].push(userIntegration);
  }

  return categories;
}

export function getIntegrationDisplayStatus(
  integration: UserIntegration,
): IntegrationStatusDisplay {
  switch (integration.status) {
    case "connected":
      return { label: "Connected", color: "green" };
    case "created":
      return { label: "Pending", color: "yellow" };
    default:
      return { label: "Unknown", color: "gray" };
  }
}

